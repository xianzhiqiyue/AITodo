from enum import Enum


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    TASK_DEPENDENCY_NOT_FOUND = "TASK_DEPENDENCY_NOT_FOUND"
    HAS_CHILDREN = "HAS_CHILDREN"
    PARENT_NOT_DONE = "PARENT_NOT_DONE"
    MAX_DEPTH_EXCEEDED = "MAX_DEPTH_EXCEEDED"
    TASK_CYCLE_DETECTED = "TASK_CYCLE_DETECTED"
    TASK_DEPENDENCY_CYCLE = "TASK_DEPENDENCY_CYCLE"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


HTTP_STATUS_MAP: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.TASK_NOT_FOUND: 404,
    ErrorCode.TASK_DEPENDENCY_NOT_FOUND: 404,
    ErrorCode.HAS_CHILDREN: 409,
    ErrorCode.PARENT_NOT_DONE: 409,
    ErrorCode.MAX_DEPTH_EXCEEDED: 422,
    ErrorCode.TASK_CYCLE_DETECTED: 422,
    ErrorCode.TASK_DEPENDENCY_CYCLE: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.INTERNAL_ERROR: 500,
}


class AppError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        self.code = code
        self.message = message
        self.status_code = HTTP_STATUS_MAP.get(code, 400)
        super().__init__(message)
