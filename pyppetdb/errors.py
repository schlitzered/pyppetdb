# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from fastapi import HTTPException


class AuthenticationError(HTTPException):
    def __init__(self, msg="Invalid Username and Password"):
        super(AuthenticationError, self).__init__(status_code=401, detail=msg)


class DuplicateResource(HTTPException):
    def __init__(self, msg="Duplicate Resource"):
        super(DuplicateResource, self).__init__(status_code=400, detail=msg)


class ResourceNotFound(HTTPException):
    def __init__(self, details=None):
        if not details:
            details = "Resource not found"
        super(ResourceNotFound, self).__init__(status_code=404, detail=details)


class BackendError(HTTPException):
    def __init__(self):
        super(BackendError, self).__init__(
            status_code=500,
            detail="Internal Server Error: please contact administrator",
        )


class LdapResourceNotFound(HTTPException):
    def __init__(self):
        super(LdapResourceNotFound, self).__init__(
            status_code=400, detail="Ldap Resource not Found"
        )


class LdapInvalidDN(HTTPException):
    def __init__(self):
        super(LdapInvalidDN, self).__init__(status_code=400, detail="invalid ldap dn")


class LdapNoBackend(HTTPException):
    def __init__(self):
        super(LdapNoBackend, self).__init__(
            status_code=400,
            detail="No Ldap Backend configured, ldap operations not supported",
        )


class AdminError(HTTPException):
    def __init__(self):
        super(AdminError, self).__init__(
            status_code=403, detail="Admin Permissions required"
        )


class PermissionError(HTTPException):
    def __init__(self, msg="Permission denied"):
        super(PermissionError, self).__init__(status_code=403, detail=msg)


class CredentialError(HTTPException):
    def __init__(self):
        super(CredentialError, self).__init__(
            status_code=403, detail="Invalid or no credentials"
        )


class ClientCertError(HTTPException):
    def __init__(self, detail: str = "Client certificate required"):
        super(ClientCertError, self).__init__(status_code=403, detail=detail)


class SessionCredentialError(HTTPException):
    def __init__(self):
        super(SessionCredentialError, self).__init__(
            status_code=401, detail="No Session or API Credentials present"
        )


class QueryParamValidationError(HTTPException):
    def __init__(self, msg):
        super(QueryParamValidationError, self).__init__(status_code=422, detail=msg)


class ResourceInUse(HTTPException):
    def __init__(self, msg="Resource is still in use"):
        super(ResourceInUse, self).__init__(status_code=409, detail=msg)
