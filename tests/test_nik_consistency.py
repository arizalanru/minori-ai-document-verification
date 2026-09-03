"""Regresi NIK kosong dan konflik; tanpa API AI atau database."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.rules import evaluate_rules

class NikConsistencyTests(unittest.TestCase):
    def check_result(self,values):
        profile=json.loads((ROOT/'config/programs/demo-core-v1.json').read_text())
        docs={kind:{'version_id':kind+'-v1','review_status':'verified',
                    'fields':{'nik':{'value':value}}} for kind,value in values.items()}
        return next(r for r in evaluate_rules({'documents':docs},profile)
                    if r['rule_code']=='NIK_CONSISTENCY')
    def test_no_documents_unknown(self):
        result=self.check_result({})
        self.assertEqual(result['result'],'UNKNOWN')
        self.assertEqual(result['source_version_ids'],[])
        self.assertTrue(result['next_action'])
    def test_null_fields_unknown(self):
        self.assertEqual(self.check_result({'KTP':None,'IJAZAH':None})['result'],'UNKNOWN')
    def test_empty_fields_unknown(self):
        self.assertEqual(self.check_result({'KTP':'','IJAZAH':''})['result'],'UNKNOWN')
    def test_optional_ijazah_nik_absent(self):
        result=self.check_result({'KTP':'0000000000000001','IJAZAH':None})
        self.assertEqual(result['result'],'PASS')
        self.assertEqual(result['source_version_ids'],['KTP-v1'])
        self.assertIn('Belum ada pembandingan',result['reason'])
    def test_matching_values_pass(self):
        self.assertEqual(self.check_result({'KTP':'0000000000000001','IJAZAH':'0000000000000001'})['result'],'PASS')
    def test_conflicting_values_review(self):
        result=self.check_result({'KTP':'0000000000000001','IJAZAH':'0000000000000002'})
        self.assertEqual(result['result'],'UNKNOWN')
        self.assertTrue(result['next_action'])
if __name__=='__main__': unittest.main(verbosity=2)
