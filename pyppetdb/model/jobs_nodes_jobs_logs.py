from pydantic import BaseModel


class LogBlobGet(BaseModel):
    id: str
    data: str
