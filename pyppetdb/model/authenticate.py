from pydantic import BaseModel


class AuthenticateGetUser(BaseModel):
    user: str


class AuthenticatePost(AuthenticateGetUser):
    password: str
