#!/usr/bin/env python3
"""Erzeugt einmalig den Signierschlüssel (Keystore) für die Android-App – lokal auf deinem Rechner.

Aufruf (Windows, PowerShell):
    py -m pip install cryptography
    py tools\\keystore_erzeugen.py

Ergebnis im Benutzerordner (NICHT im Repo):
    upload-keystore.jks        der Schlüssel – sicher aufbewahren (Backup!)
    upload-keystore-base64.txt derselbe Schlüssel als Text für das GitHub-Secret

Der Schlüssel muss für alle künftigen Versionen derselbe bleiben. Geht er verloren, lässt sich
eine neue Version nur nach Deinstallation der alten installieren (dabei gehen die Projekte auf dem
Handy verloren).
"""

import base64
import datetime as dt
import secrets
import sys
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
except ImportError:
    sys.exit("Bitte zuerst installieren:  py -m pip install cryptography")

ALIAS = "upload"   # Standard-Alias von flet build


def main():
    out_dir = Path.home()
    store = out_dir / "upload-keystore.jks"
    b64 = out_dir / "upload-keystore-base64.txt"
    if store.exists():
        sys.exit(f"{store} existiert bereits – nicht überschrieben. (Gibt es schon einen Schlüssel, diesen weiter benutzen.)")

    password = secrets.token_urlsafe(18)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WikiTree GEDCOM Vergleich")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=10000))
            .sign(key, hashes.SHA256()))
    # PKCS12 – Java (und damit der Android-Build) liest das auch unter der Endung .jks
    enc = (serialization.PrivateFormat.PKCS12.encryption_builder()
           .kdf_rounds(50000)
           .key_cert_algorithm(pkcs12.PBES.PBESv2SHA256AndAES256CBC)
           .hmac_hash(hashes.SHA256())
           .build(password.encode()))
    data = pkcs12.serialize_key_and_certificates(ALIAS.encode(), key, cert, None, enc)
    store.write_bytes(data)
    b64.write_text(base64.b64encode(data).decode(), encoding="ascii")

    print(f"""
Fertig.
  Keystore:            {store}
  Als Text (Secret):   {b64}

Jetzt auf GitHub im Repo: Settings -> Secrets and variables -> Actions -> New repository secret
  Name: ANDROID_KEYSTORE_BASE64     Wert: kompletter Inhalt von {b64.name}
  Name: ANDROID_KEYSTORE_PASSWORD   Wert: {password}

Das Passwort steht nur hier – notiere es sicher (z. B. im Passwortmanager) zusammen mit einem
Backup von {store.name}. Die Datei {b64.name} kannst du danach löschen.
""")


if __name__ == "__main__":
    main()
