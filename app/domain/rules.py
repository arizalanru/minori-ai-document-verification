"""Aturan deterministik tanpa akses AI atau database."""

import re
from datetime import date


def calculate_age(birth_date, reference_date):
    if birth_date > reference_date:
        raise ValueError("Tanggal lahir di masa depan")
    before_birthday = (reference_date.month, reference_date.day) < (
        birth_date.month,
        birth_date.day,
    )
    return reference_date.year - birth_date.year - before_birthday


def evaluate_rules(snapshot, profile):
    documents = snapshot["documents"]
    results = []

    def add(code, result, reason, document_types=(), action=""):
        results.append(
            {
                "rule_code": code,
                "result": result,
                "reason": reason,
                "source_version_ids": [
                    documents[document_type]["version_id"]
                    for document_type in document_types
                    if document_type in documents
                ],
                "next_action": action,
            }
        )

    def value(document_type, field_name):
        return (
            documents.get(document_type, {})
            .get("fields", {})
            .get(field_name, {})
            .get("value")
        )

    def is_verified(document_type):
        return documents.get(document_type, {}).get("review_status") == "verified"

    required_documents = profile["required_documents"]
    missing = [kind for kind in required_documents if kind not in documents]
    pending = [
        kind
        for kind in required_documents
        if kind in documents and not is_verified(kind)
    ]
    add(
        "REQUIRED_DOCUMENTS",
        "UNKNOWN" if missing or pending else "PASS",
        f"Belum ada: {', '.join(missing) or '-'}; "
        f"belum verified: {', '.join(pending) or '-'}",
        required_documents,
        "Lengkapi/periksa dokumen" if missing or pending else "",
    )

    nik = value("KTP", "nik")
    add(
        "NIK_FORMAT",
        "UNKNOWN"
        if not nik or not is_verified("KTP")
        else ("PASS" if re.fullmatch(r"[0-9]{16}", nik) else "FAIL"),
        "NIK wajib 16 digit dan dikonfirmasi; bukan pemeriksaan keaslian",
        ("KTP",),
    )

    other_nik = value("IJAZAH", "nik")
    nik_conflict = bool(nik and other_nik and nik != other_nik)
    nik_sources = tuple(
        kind for kind in ("KTP", "IJAZAH") if value(kind, "nik")
    )
    if not nik_sources:
        add(
            "NIK_CONSISTENCY",
            "UNKNOWN",
            "Belum ada NIK untuk diperiksa",
            action="Lengkapi/periksa NIK pada KTP",
        )
    elif nik_conflict:
        add(
            "NIK_CONSISTENCY",
            "UNKNOWN",
            "NIK berbeda antardokumen",
            nik_sources,
            "Periksa NIK pada kedua gambar sumber",
        )
    else:
        # Ijazah tidak wajib memuat NIK; konflik diperiksa dari sumber yang ada.
        reason = (
            "NIK sama pada kedua sumber"
            if len(nik_sources) == 2
            else "Hanya satu sumber NIK tersedia; tidak ada konflik yang "
            "terdeteksi. Belum ada pembandingan antardokumen"
        )
        add("NIK_CONSISTENCY", "PASS", reason, nik_sources)

    names = [value(kind, "nama") for kind in ("KTP", "IJAZAH")]
    names_match = all(names) and len(
        {" ".join(name.upper().split()) for name in names}
    ) == 1
    add(
        "IDENTITY_CONSISTENCY",
        "PASS" if names_match else "UNKNOWN",
        "Nama sesuai" if names_match else "Nama belum lengkap atau berbeda",
        ("KTP", "IJAZAH"),
        "Periksa kedua sumber" if not names_match else "",
    )

    birth_date = value("KTP", "tanggal_lahir")
    other_birth_date = value("IJAZAH", "tanggal_lahir")
    age = None
    if (
        birth_date
        and is_verified("KTP")
        and not (other_birth_date and birth_date != other_birth_date)
    ):
        try:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", birth_date):
                raise ValueError()
            age = calculate_age(
                date.fromisoformat(birth_date),
                date.fromisoformat(profile["reference_date"]),
            )
        except ValueError:
            add(
                "BIRTH_DATE",
                "FAIL",
                "Tanggal dikonfirmasi tetapi tidak sah/di masa depan",
                ("KTP",),
            )
        else:
            add("BIRTH_DATE", "PASS", "Tanggal valid", ("KTP",))
    else:
        add(
            "BIRTH_DATE",
            "UNKNOWN",
            "Tanggal hilang, belum dikonfirmasi, atau konflik",
            ("KTP", "IJAZAH"),
            "Periksa tanggal lahir",
        )

    add(
        "AGE_RANGE",
        "UNKNOWN"
        if age is None
        else ("PASS" if profile["age_min"] <= age <= profile["age_max"] else "FAIL"),
        f"Usia {age if age is not None else 'belum pasti'} pada "
        f"{profile['reference_date']}; rentang demo "
        f"{profile['age_min']}-{profile['age_max']}",
        ("KTP",),
    )

    education = value("IJAZAH", "pendidikan_terakhir")
    education_rank = (
        profile["education_rank"].get(education.strip().upper())
        if education
        else None
    )
    add(
        "EDUCATION_MIN",
        "UNKNOWN"
        if education_rank is None or not is_verified("IJAZAH")
        else (
            "PASS"
            if education_rank
            >= profile["education_rank"][profile["minimum_education"]]
            else "FAIL"
        ),
        f"Pendidikan {education or 'belum terbaca'}; "
        f"minimum demo {profile['minimum_education']}",
        ("IJAZAH",),
    )

    required_fields = {
        "KTP": ("nama", "nik", "tanggal_lahir", "alamat"),
        "IJAZAH": ("nama", "pendidikan_terakhir", "nomor_dokumen"),
    }
    empty_fields = [
        f"{document_type}.{field_name}"
        for document_type, field_names in required_fields.items()
        for field_name in field_names
        if not value(document_type, field_name)
    ]
    add(
        "REQUIRED_FIELDS",
        "UNKNOWN" if empty_fields else "PASS",
        "Field kosong: " + ", ".join(empty_fields)
        if empty_fields
        else "Field wajib tersedia",
        ("KTP", "IJAZAH"),
    )
    return results


def aggregate(results):
    if any(result["result"] == "FAIL" for result in results):
        return "FLAGGED"
    if not results or any(result["result"] == "UNKNOWN" for result in results):
        return "REVIEW"
    return "ELIGIBLE"
