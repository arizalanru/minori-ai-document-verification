"""Tes services + SQLite nyata, adapter OCR/LLM SIMULATED. Bukan uji HTTP/AI live."""
import copy
import sys
import tempfile
import unittest
from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.errors import DomainError
from app.domain.rules import calculate_age
from app.services.backend import Backend

VALUES={'nama':'PESERTA DEMO A','nik':'0000000000000001','tanggal_lahir':'2006-05-21',
        'alamat':'JALAN CONTOH NOMOR 1','pendidikan_terakhir':'SMA','nomor_dokumen':'DEMO-IJZ-001'}
BLOCKS=[dict(block_id=f'b{i+1}',page_number=1,text=v,confidence=.99,polygon=None)
        for i,v in enumerate(VALUES.values())]
class FakeOCR:
    def extract(self,path): return copy.deepcopy(BLOCKS)
class FakeLLM:
    metadata={'test_fixture':True}
    def extract(self,kind,blocks):
        data={k:dict(value=v,raw_text=v,status='extracted',evidence_ids=[f'b{i+1}'],reason_code='NONE')
              for i,(k,v) in enumerate(VALUES.items())}
        if kind=='KTP':
            data['pendidikan_terakhir']=dict(value=None,raw_text=None,status='not_applicable',evidence_ids=[],reason_code='NOT_EXPECTED')
        return data
class Settings:
    database_path=Path('app.sqlite3'); private_files_dir=Path('files')
    max_upload_bytes=10*1024*1024; max_image_pixels=20_000_000
    gemini_model='TEST-NO-MODEL'; ocr_timeout_seconds=60
    def __init__(self,tmp): self.tmp=Path(tmp)
    def resolve_path(self,p): return self.tmp/p

def image_bytes(color='white'):
    out=BytesIO(); Image.new('RGB',(50,50),color).save(out,format='PNG'); return out.getvalue()

class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.backend=Backend(Settings(self.tmp.name),ROOT,FakeOCR,FakeLLM)
        self.backend.initialize(); self.aid=self.backend.create('demo-core-v1')['application_id']
    def tearDown(self): self.tmp.cleanup()
    def rev(self,aid=None): return self.backend.get(aid or self.aid)['revision']
    def upload(self,kind='KTP',aid=None,color='white'):
        aid=aid or self.aid
        return self.backend.upload(aid,kind,image_bytes(color),self.rev(aid))['version_id']
    def prepare(self,kind):
        vid=self.upload(kind)
        out=self.backend.process(vid,self.rev())
        self.assertEqual(out['status'],'SUCCEEDED')
        return vid
    def verify(self,vid,corrections=None):
        return self.backend.review(self.aid,vid,'verify',corrections or {},'Diperiksa pada dokumen dummy',self.rev())
    def setup_clean(self):
        ktp=self.prepare('KTP'); self.verify(ktp)
        ijz=self.prepare('IJAZAH'); self.verify(ijz)
        return ktp,ijz
    def test_clean_requires_review_then_eligible(self):
        ktp=self.prepare('KTP'); ijz=self.prepare('IJAZAH')
        self.assertEqual(self.backend.get(self.aid)['outcome'],'REVIEW')
        self.verify(ktp); self.verify(ijz)
        self.assertEqual(self.backend.get(self.aid)['outcome'],'ELIGIBLE')
    def test_age_boundaries(self):
        for dob,age in [('2008-09-04',18),('2008-09-05',17),('1996-09-04',30),('1995-09-05',30),('1995-09-04',31)]:
            with self.subTest(dob=dob): self.assertEqual(calculate_age(date.fromisoformat(dob),date(2026,9,4)),age)
        self.assertEqual(calculate_age(date(2004,2,29),date(2025,2,28)),20)
        self.assertEqual(calculate_age(date(2004,2,29),date(2025,3,1)),21)
    def test_negative_age_and_confirmation(self):
        ktp,ijz=self.setup_clean()
        self.verify(ijz,{'tanggal_lahir':None})
        self.verify(ktp,{'tanggal_lahir':'2010-01-01'})
        out=self.backend.get(self.aid); self.assertEqual(out['outcome'],'FLAGGED')
        self.backend.confirm(self.aid,out['evaluation']['evaluation_id'],'Batas usia demo',out['revision'])
        self.assertEqual(self.backend.get(self.aid)['outcome'],'INELIGIBLE')
    def test_conflicting_birthdate_unknown(self):
        ktp,ijz=self.setup_clean(); self.verify(ktp,{'tanggal_lahir':'2010-01-01'})
        results=self.backend.get(self.aid)['evaluation']['results']
        self.assertEqual(next(r['result'] for r in results if r['rule_code']=='AGE_RANGE'),'UNKNOWN')
    def test_missing_documents_full(self):
        self.setup_clean()
        self.backend.change_profile(self.aid,'demo-full-v1',self.rev(),'Profil lengkap')
        out=self.backend.get(self.aid)
        self.assertEqual(out['outcome'],'REVIEW'); self.assertEqual(len(out['missing_documents']),4)
    def test_extended_doc_requires_its_schema(self):
        vid=self.upload('MCU'); out=self.backend.process(vid,self.rev())
        self.assertEqual(out['status'],'FAILED')
        self.assertEqual(self.backend.extraction(vid)['review_status'],'needs_review')
    def test_bad_evidence_fails_without_eligibility(self):
        class Bad(FakeLLM):
            def extract(self,k,b):
                d=super().extract(k,b); d['nama']['evidence_ids']=['invented']; return d
        self.backend.llm_factory=Bad
        vid=self.upload(); out=self.backend.process(vid,self.rev())
        self.assertEqual(out['error_code'],'OUTPUT_INVALID')
        self.assertEqual(self.backend.get(self.aid)['outcome'],'REVIEW')
    def test_provider_error_persisted(self):
        class Busy(FakeLLM):
            def extract(self,k,b): raise DomainError('PROVIDER_BUSY','Tidak tersedia',503)
        self.backend.llm_factory=Busy
        vid=self.upload(); out=self.backend.process(vid,self.rev())
        self.assertEqual(out['status'],'FAILED'); self.assertEqual(out['error_code'],'PROVIDER_BUSY')
    def test_correction_preserves_raw(self):
        vid=self.prepare('KTP'); self.verify(vid,{'nama':'PESERTA DEMO B'})
        out=self.backend.extraction(vid)
        self.assertEqual(out['fields']['nama']['value'],'PESERTA DEMO A')
        self.assertEqual(out['corrections']['nama']['value'],'PESERTA DEMO B')
        self.assertTrue(self.backend.history(self.aid)['reviews'])
    def test_upload_idempotency(self):
        before=self.rev(); data=image_bytes()
        a=self.backend.upload(self.aid,'KTP',data,before,'same')
        b=self.backend.upload(self.aid,'KTP',data,before,'same')
        self.assertEqual(a,b)
        with self.assertRaises(DomainError): self.backend.upload(self.aid,'KTP',image_bytes('red'),before,'same')
        self.assertEqual(self.rev(),before+1)
    def test_process_idempotency(self):
        vid=self.upload(); revision=self.rev()
        a=self.backend.process(vid,revision,'same'); b=self.backend.process(vid,revision,'same')
        self.assertEqual(a['process_run_id'],b['process_run_id'])
        self.assertEqual(len(self.backend.extraction(vid)['runs']),1)
    def test_replacement_resets_review(self):
        ktp,ijz=self.setup_clean(); new=self.upload('KTP',color='red')
        self.assertNotEqual(ktp,new)
        self.assertEqual(self.backend.get(self.aid)['outcome'],'PENDING')
        self.assertEqual(self.backend.extraction(new)['review_status'],'uploaded')
    def test_cross_application_review_blocked(self):
        vid=self.prepare('KTP'); other=self.backend.create('demo-core-v1')['application_id']
        with self.assertRaises(DomainError): self.backend.review(other,vid,'verify',{},'test',0)
        self.assertEqual(self.rev(other),0)
    def test_invalid_file_no_revision(self):
        with self.assertRaises(DomainError): self.backend.upload(self.aid,'KTP',b'not an image',0)
        self.assertEqual(self.rev(),0)
    def test_confirm_without_fail_blocked(self):
        self.setup_clean(); out=self.backend.get(self.aid)
        with self.assertRaises(DomainError): self.backend.confirm(self.aid,out['evaluation']['evaluation_id'],'test',out['revision'])
    def test_stale_ai_cannot_overwrite_review(self):
        vid=self.upload(); backend=self.backend; aid=self.aid
        class Late(FakeLLM):
            def extract(self,k,b):
                backend.review(aid,vid,'verify',VALUES.copy(),'Manual saat proses berjalan',backend.get(aid)['revision'])
                return super().extract(k,b)
        self.backend.llm_factory=Late
        out=self.backend.process(vid,self.rev())
        self.assertFalse(out['published'])
        state=self.backend.extraction(vid)
        self.assertEqual(state['review_status'],'verified'); self.assertEqual(state['fields'],{})
        self.assertEqual(state['corrections']['nama']['value'],VALUES['nama'])
    def test_invalid_revision_blocked(self):
        vid=self.upload()
        with self.assertRaises(DomainError): self.backend.process(vid,0)
    def test_restart_marks_interrupted(self):
        vid=self.upload()
        with self.backend.db.transaction() as c:
            c.execute("INSERT INTO process_runs(id,version_id,status,input_revision,metadata_json,started_at) VALUES(?,?,'RUNNING',1,'{}','test')",('interrupted',vid))
        self.backend.initialize()
        self.assertEqual(self.backend.get_run('interrupted')['error_code'],'PROCESS_INTERRUPTED')
    def test_education_and_name_conflict(self):
        ktp,ijz=self.setup_clean()
        self.verify(ijz,{'pendidikan_terakhir':'SMP','nama':'ORANG LAIN'})
        out=self.backend.get(self.aid)
        self.assertEqual(out['outcome'],'FLAGGED')
        self.assertTrue(any(r['result']=='UNKNOWN' and r['rule_code']=='IDENTITY_CONSISTENCY' for r in out['evaluation']['results']))
    def test_nik_conflict_blocks_eligibility(self):
        ktp,ijz=self.setup_clean()
        self.verify(ijz,{'nik':'0000000000000002'})
        self.assertEqual(self.backend.get(self.aid)['outcome'],'REVIEW')
    def test_same_image_different_app_not_deduped(self):
        v1=self.upload(); other=self.backend.create('demo-core-v1')['application_id']; v2=self.upload(aid=other)
        self.assertNotEqual(v1,v2)

if __name__=='__main__': unittest.main(verbosity=2)
