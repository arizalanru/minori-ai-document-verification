from enum import Enum


class ProcessStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    MANUAL_ONLY = "MANUAL_ONLY"


class DocumentStatus(str, Enum):
    MISSING = "missing"
    UPLOADED = "uploaded"
    NEEDS_REVIEW = "needs_review"
    VERIFIED = "verified"


class RuleResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class ApplicationOutcome(str, Enum):
    PENDING = "PENDING"
    REVIEW = "REVIEW"
    FLAGGED = "FLAGGED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
