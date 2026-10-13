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

import datetime
import re
import uuid
from typing import Any
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.types import (
    CertificateIssuerPrivateKeyTypes,
)
from cryptography.x509.oid import NameOID

CertificateInput = Union[bytes, x509.Certificate]
IssuerKeyInput = Union[bytes, CertificateIssuerPrivateKeyTypes]

KEY_SIZE = 4096
PUBLIC_EXPONENT = 65537


def load_certificate(cert: CertificateInput) -> x509.Certificate:
    if isinstance(cert, bytes):
        return x509.load_pem_x509_certificate(data=cert.strip())
    return cert


def load_private_key(key: IssuerKeyInput) -> CertificateIssuerPrivateKeyTypes:
    if isinstance(key, bytes):
        return serialization.load_pem_private_key(data=key, password=None)
    return key


def _new_private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(
        public_exponent=PUBLIC_EXPONENT,
        key_size=KEY_SIZE,
    )


def _private_key_pem(private_key: rsa.RSAPrivateKey) -> bytes:
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )


def build_name(
    cn: str,
    organization: str,
    organizational_unit: str,
    country: str,
    state: Optional[str] = None,
    locality: Optional[str] = None,
) -> x509.Name:
    attributes = [
        x509.NameAttribute(oid=NameOID.COMMON_NAME, value=cn),
        x509.NameAttribute(oid=NameOID.ORGANIZATION_NAME, value=organization),
        x509.NameAttribute(
            oid=NameOID.ORGANIZATIONAL_UNIT_NAME, value=organizational_unit
        ),
        x509.NameAttribute(oid=NameOID.COUNTRY_NAME, value=country),
    ]
    if state:
        attributes.append(
            x509.NameAttribute(oid=NameOID.STATE_OR_PROVINCE_NAME, value=state)
        )
    if locality:
        attributes.append(x509.NameAttribute(oid=NameOID.LOCALITY_NAME, value=locality))
    return x509.Name(attributes=attributes)


def common_name(name: x509.Name) -> str:
    return str(name.get_attributes_for_oid(oid=NameOID.COMMON_NAME)[0].value)


def ca_key_usage() -> x509.KeyUsage:
    return x509.KeyUsage(
        digital_signature=True,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=True,
        crl_sign=True,
        encipher_only=False,
        decipher_only=False,
    )


def generate_csr(
    cn: str,
    organization: str = "PyppetDB",
    organizational_unit: str = "Nodes",
    country: str = "DE",
    state: Optional[str] = "Hessen",
    locality: Optional[str] = None,
    alt_names: Optional[List[str]] = None,
) -> Tuple[bytes, bytes]:
    private_key = _new_private_key()
    builder = x509.CertificateSigningRequestBuilder().subject_name(
        name=build_name(cn, organization, organizational_unit, country, state, locality)
    )
    if alt_names:
        builder = builder.add_extension(
            extval=x509.SubjectAlternativeName(
                general_names=[x509.DNSName(value=name) for name in alt_names]
            ),
            critical=False,
        )
    csr = builder.sign(private_key=private_key, algorithm=hashes.SHA256())
    return (
        csr.public_bytes(encoding=serialization.Encoding.PEM),
        _private_key_pem(private_key),
    )


def generate_ca(
    cn: str,
    organization: str = "PyppetDB",
    organizational_unit: str = "CA",
    country: str = "DE",
    state: Optional[str] = "Hessen",
    locality: Optional[str] = None,
    validity_days: int = 3650,
    issuer_cert: Optional[CertificateInput] = None,
    issuer_key: Optional[IssuerKeyInput] = None,
) -> Tuple[bytes, bytes]:
    private_key = _new_private_key()
    subject = build_name(cn, organization, organizational_unit, country, state, locality)
    if issuer_cert is None:
        issuer_name = subject
        issuer_public_key = private_key.public_key()
        signing_key = private_key
    else:
        parent = load_certificate(issuer_cert)
        issuer_name = parent.subject
        issuer_public_key = parent.public_key()
        signing_key = load_private_key(issuer_key)
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name=subject)
        .issuer_name(name=issuer_name)
        .public_key(key=private_key.public_key())
        .serial_number(number=uuid.uuid4().int)
        .not_valid_before(time=now)
        .not_valid_after(time=now + datetime.timedelta(days=validity_days))
        .add_extension(
            extval=x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
        .add_extension(extval=ca_key_usage(), critical=True)
        .add_extension(
            extval=x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()),
            critical=False,
        )
        .add_extension(
            extval=x509.AuthorityKeyIdentifier.from_issuer_public_key(
                issuer_public_key
            ),
            critical=False,
        )
        .sign(private_key=signing_key, algorithm=hashes.SHA256())
    )
    return (
        cert.public_bytes(encoding=serialization.Encoding.PEM),
        _private_key_pem(private_key),
    )


def sign_ca(
    cn: str,
    ca_cert: CertificateInput,
    ca_key: IssuerKeyInput,
    organization: str = "PyppetDB",
    organizational_unit: str = "CA",
    country: str = "DE",
    state: Optional[str] = "Hessen",
    locality: Optional[str] = None,
    validity_days: int = 3650,
) -> Tuple[bytes, bytes]:
    return generate_ca(
        cn=cn,
        organization=organization,
        organizational_unit=organizational_unit,
        country=country,
        state=state,
        locality=locality,
        validity_days=validity_days,
        issuer_cert=ca_cert,
        issuer_key=ca_key,
    )


def _san_values(extensions: x509.Extensions) -> Optional[x509.Extension]:
    try:
        return extensions.get_extension_for_class(extclass=x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return None


def parse_and_extract_csr(
    csr_pem: bytes,
) -> Tuple[x509.CertificateSigningRequest, dict]:
    csr = x509.load_pem_x509_csr(data=csr_pem)
    if not csr.is_signature_valid:
        raise ValueError("CSR signature is invalid")
    san_extension = _san_values(csr.extensions)
    sans = [str(name.value) for name in san_extension.value] if san_extension else []
    return csr, {"cn": common_name(csr.subject), "sans": sans}


def csr_dns_sans(csr: x509.CertificateSigningRequest) -> List[str]:
    san_extension = _san_values(csr.extensions)
    if san_extension is None:
        return []
    return san_extension.value.get_values_for_type(x509.DNSName)


def csr_pem_dns_sans(csr_pem: bytes) -> List[str]:
    return csr_dns_sans(x509.load_pem_x509_csr(data=csr_pem.strip()))


def certificate_dns_sans(cert: CertificateInput) -> List[str]:
    san_extension = _san_values(load_certificate(cert).extensions)
    if san_extension is None:
        return []
    return san_extension.value.get_values_for_type(x509.DNSName)


def _extended_key_usages(names: List[str]) -> List[x509.ObjectIdentifier]:
    usages = []
    for name in names:
        if hasattr(x509.ExtendedKeyUsageOID, name):
            usages.append(getattr(x509.ExtendedKeyUsageOID, name))
        else:
            usages.append(x509.ObjectIdentifier(value=name))
    return usages


def _subject_alternative_names(
    cn: str,
    requested_sans: List[str],
    injected_sans: Optional[List[str]],
) -> List[x509.DNSName]:
    names: List[str] = list(requested_sans)
    if cn not in names:
        names.append(cn)
    for san in injected_sans or []:
        if san not in names:
            names.append(san)
    return [x509.DNSName(value=name) for name in names]


def _build_and_sign_certificate(
    subject: x509.Name,
    public_key: Any,
    extensions: x509.Extensions,
    ca_cert: CertificateInput,
    ca_key: IssuerKeyInput,
    key_usages: dict[str, bool],
    extended_key_usages: List[str],
    validity_days: int = 365,
    serial_number: Optional[int] = None,
    allowed_extensions: Optional[List[str]] = None,
    injected_sans: Optional[List[str]] = None,
    requested_sans: Optional[List[str]] = None,
    requested_sans_critical: bool = False,
) -> bytes:
    ca_cert = load_certificate(ca_cert)
    ca_key = load_private_key(ca_key)
    if serial_number is None:
        serial_number = uuid.uuid4().int
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    requested_sans = requested_sans or []
    builder = (
        x509.CertificateBuilder()
        .subject_name(name=subject)
        .issuer_name(name=ca_cert.subject)
        .public_key(key=public_key)
        .serial_number(number=serial_number)
        .not_valid_before(time=now)
        .not_valid_after(time=now + datetime.timedelta(days=validity_days))
        .add_extension(
            extval=x509.BasicConstraints(ca=False, path_length=None), critical=True
        )
        .add_extension(extval=x509.KeyUsage(**key_usages), critical=True)
        .add_extension(
            extval=x509.SubjectAlternativeName(
                general_names=_subject_alternative_names(
                    common_name(subject), requested_sans, injected_sans
                )
            ),
            critical=requested_sans_critical and bool(requested_sans),
        )
        .add_extension(
            extval=x509.SubjectKeyIdentifier.from_public_key(public_key),
            critical=False,
        )
        .add_extension(
            extval=x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_cert.public_key()
            ),
            critical=False,
        )
    )
    if extended_key_usages:
        builder = builder.add_extension(
            extval=x509.ExtendedKeyUsage(
                usages=_extended_key_usages(extended_key_usages)
            ),
            critical=False,
        )
    if allowed_extensions:
        for extension in extensions:
            if isinstance(
                extension.value,
                (
                    x509.SubjectAlternativeName,
                    x509.SubjectKeyIdentifier,
                    x509.AuthorityKeyIdentifier,
                ),
            ):
                continue
            if extension.oid.dotted_string in allowed_extensions:
                builder = builder.add_extension(
                    extval=extension.value, critical=extension.critical
                )
    cert = builder.sign(private_key=ca_key, algorithm=hashes.SHA256())
    return cert.public_bytes(encoding=serialization.Encoding.PEM)


def sign_csr(
    csr: Union[bytes, x509.CertificateSigningRequest],
    ca_cert: CertificateInput,
    ca_key: IssuerKeyInput,
    key_usages: dict[str, bool],
    extended_key_usages: List[str],
    validity_days: int = 365,
    serial_number: Optional[int] = None,
    allowed_extensions: Optional[List[str]] = None,
    injected_sans: Optional[List[str]] = None,
    honor_csr_sans: bool = True,
) -> bytes:
    if isinstance(csr, bytes):
        csr = x509.load_pem_x509_csr(data=csr.strip())
    san_extension = _san_values(csr.extensions)
    return _build_and_sign_certificate(
        subject=csr.subject,
        public_key=csr.public_key(),
        extensions=csr.extensions,
        ca_cert=ca_cert,
        ca_key=ca_key,
        key_usages=key_usages,
        extended_key_usages=extended_key_usages,
        validity_days=validity_days,
        serial_number=serial_number,
        allowed_extensions=allowed_extensions,
        injected_sans=injected_sans,
        requested_sans=csr_dns_sans(csr) if honor_csr_sans else [],
        requested_sans_critical=bool(san_extension and san_extension.critical),
    )


def renew_cert(
    cert: CertificateInput,
    ca_cert: CertificateInput,
    ca_key: IssuerKeyInput,
    key_usages: dict[str, bool],
    extended_key_usages: List[str],
    validity_days: int = 365,
    serial_number: Optional[int] = None,
    allowed_extensions: Optional[List[str]] = None,
    injected_sans: Optional[List[str]] = None,
    honor_cert_sans: bool = True,
    requested_sans: Optional[List[str]] = None,
) -> bytes:
    cert = load_certificate(cert)
    san_extension = _san_values(cert.extensions)
    if requested_sans is None:
        requested_sans = certificate_dns_sans(cert)
    return _build_and_sign_certificate(
        subject=cert.subject,
        public_key=cert.public_key(),
        extensions=cert.extensions,
        ca_cert=ca_cert,
        ca_key=ca_key,
        key_usages=key_usages,
        extended_key_usages=extended_key_usages,
        validity_days=validity_days,
        serial_number=serial_number,
        allowed_extensions=allowed_extensions,
        injected_sans=injected_sans,
        requested_sans=requested_sans if honor_cert_sans else [],
        requested_sans_critical=bool(san_extension and san_extension.critical),
    )


def get_cert_info(cert_pem: bytes) -> dict:
    cert = load_certificate(cert_pem)
    san_extension = _san_values(cert.extensions)
    sans = [str(name.value) for name in san_extension.value] if san_extension else []
    return {
        "cn": common_name(cert.subject),
        "issuer": cert.issuer.rfc4514_string(),
        "serial_number": str(cert.serial_number),
        "not_before": cert.not_valid_before_utc,
        "not_after": cert.not_valid_after_utc,
        "fingerprint": {
            "sha256": cert.fingerprint(algorithm=hashes.SHA256()).hex(),
            "sha1": cert.fingerprint(algorithm=hashes.SHA1()).hex(),
            "md5": cert.fingerprint(algorithm=hashes.MD5()).hex(),
        },
        "sans": sans,
    }


def generate_crl(
    ca_cert: CertificateInput,
    ca_key: IssuerKeyInput,
    revoked_certs: List[dict],
    validity_days: int = 30,
) -> Tuple[bytes, datetime.datetime]:
    ca_cert = load_certificate(ca_cert)
    ca_key = load_private_key(ca_key)
    last_update = datetime.datetime.now(tz=datetime.timezone.utc)
    next_update = last_update + datetime.timedelta(days=validity_days)
    builder = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(issuer_name=ca_cert.subject)
        .last_update(last_update=last_update)
        .next_update(next_update=next_update)
        .add_extension(
            extval=x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_cert.public_key()
            ),
            critical=False,
        )
    )
    for revoked in revoked_certs:
        builder = builder.add_revoked_certificate(
            revoked_certificate=x509.RevokedCertificateBuilder()
            .serial_number(number=revoked["serial_number"])
            .revocation_date(time=revoked["revocation_date"])
            .build()
        )
    crl = builder.sign(private_key=ca_key, algorithm=hashes.SHA256())
    return crl.public_bytes(encoding=serialization.Encoding.PEM), next_update


def key_matches_certificate(cert: CertificateInput, key: IssuerKeyInput) -> bool:
    public_format = serialization.PublicFormat.SubjectPublicKeyInfo
    certificate_key = load_certificate(cert).public_key()
    private_key = load_private_key(key).public_key()
    return certificate_key.public_bytes(
        encoding=serialization.Encoding.DER, format=public_format
    ) == private_key.public_bytes(
        encoding=serialization.Encoding.DER, format=public_format
    )


def issued_by(cert: CertificateInput, issuer: CertificateInput) -> bool:
    try:
        load_certificate(cert).verify_directly_issued_by(load_certificate(issuer))
    except (ValueError, TypeError, InvalidSignature):
        return False
    return True


def revoked_serials_from_crls(crl_pem: bytes, issuer: CertificateInput) -> set[int]:
    issuer = load_certificate(issuer)
    serials: set[int] = set()
    for block in re.findall(
        rb"-----BEGIN X509 CRL-----.*?-----END X509 CRL-----", crl_pem, re.DOTALL
    ):
        crl = x509.load_pem_x509_crl(block)
        if crl.issuer != issuer.subject or not crl.is_signature_valid(
            issuer.public_key()
        ):
            continue
        serials.update(revoked.serial_number for revoked in crl)
    return serials
