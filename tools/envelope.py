"""Signierter Umschlag: Nutzdaten + Ed25519-Signatur in EINEM Dokument.

Warum ein Umschlag und keine `.sig`-Beidatei (ADR 0006 §2): Bei zwei Abrufen
kann dazwischen veröffentlicht werden. Der Client hält dann neue Nutzdaten
mit alter Signatur in der Hand und verwirft einen gültigen Stand — oder,
schlimmer, jemand serviert ihm absichtlich ein zerrissenes Paar. Ein Abruf, ein
Dokument, eine Entscheidung.

Signiert werden die **rohen Bytes** von `defects.json`, nicht deren
Base64-Darstellung. Damit gilt die Prüfkette, die jeder nachgehen kann:

    base64decode(envelope.payload) == bytes(defects.json)   # Byte für Byte
    ed25519_verify(pubkey[keyId], envelope.sig, jene Bytes)

Kein CA, kein OCSP, keine Ablaufdaten. Ein Schlüsselpaar, dessen öffentlicher
Teil im Client-Binary liegt — und ein Reserveschlüssel daneben.

**`keyEpoch` ist der Widerruf.** Ein zweiter Schlüssel im Binary allein
widerruft nichts: die App vertraut dann eben beiden, und wer K1 gestohlen hat,
signiert weiter gültig. Deshalb trägt jeder Umschlag eine aufsteigende Epoche
(K1 = 1, K2 = 2). Der Client merkt sich die höchste Epoche, die er je gültig
gesehen hat, und weist danach jede niedrigere ab. Sobald ein Gerät einmal
einen K2-Stand gesehen hat, ist K1 für dieses Gerät tot — ohne App-Update,
ohne Widerrufsserver.

Die Grenze davon, ehrlich benannt: ein Gerät, das den K2-Stand nie zu sehen
bekommt (weil ein Angreifer das Netz kontrolliert), bleibt bei K1. Gegen einen
dauerhaften Netzangreifer hilft nur das App-Update. Gegen den realistischen
Fall — gestohlener Schlüssel, Angreifer kann nicht jedes Gerät dauerhaft vom
Netz trennen — wirkt die Epoche sofort.
"""

import base64
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

ENVELOPE_VERSION = 1
ALG = "ed25519"

# Schlüssel → Epoche. Aufsteigend, niemals wiederverwendet. Ein Eintrag hier
# ist eine Zusage an alle ausgelieferten Apps: wer einmal Epoche N gesehen hat,
# nimmt N-1 nie wieder an.
KEY_EPOCHS = {"k1": 1, "k2": 2}


class SigningError(RuntimeError):
    """Signieren oder Prüfen fehlgeschlagen. Bewusst eigene Klasse: der
    Aufrufer soll einen Signaturfehler NIE mit einem Netz- oder Parse-Fehler
    verwechseln und stillschweigend weiterlaufen."""


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str, label: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except Exception as exc:  # noqa: BLE001 — Ursache egal, Befund zählt
        raise SigningError(f"{label}: kein gültiges Base64") from exc


def load_private_key(pem: bytes) -> Ed25519PrivateKey:
    """PEM (aus `openssl genpkey -algorithm ed25519`) → Schlüssel.

    Nimmt bewusst nur Ed25519 an: ein versehentlich hinterlegter RSA- oder
    P-256-Schlüssel soll hier scheitern und nicht erst beim Client.
    """
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningError(f"Kein Ed25519-Schlüssel, sondern {type(key).__name__}")
    return key


def load_public_key(raw_or_pem: bytes) -> Ed25519PublicKey:
    """Akzeptiert die 32 rohen Bytes ODER ein PEM — beides kommt vor: das
    Binary trägt die rohen Bytes, Menschen tauschen PEM."""
    if len(raw_or_pem) == 32:
        return Ed25519PublicKey.from_public_bytes(raw_or_pem)
    key = serialization.load_pem_public_key(raw_or_pem)
    if not isinstance(key, Ed25519PublicKey):
        raise SigningError(f"Kein Ed25519-Schlüssel, sondern {type(key).__name__}")
    return key


def public_raw(key: Ed25519PublicKey | Ed25519PrivateKey) -> bytes:
    """Die 32 Bytes, die ins App-Binary gehören."""
    if isinstance(key, Ed25519PrivateKey):
        key = key.public_key()
    return key.public_bytes(serialization.Encoding.Raw,
                            serialization.PublicFormat.Raw)


def fingerprint(key: Ed25519PublicKey | Ed25519PrivateKey) -> str:
    """Kurzer, von Hand vergleichbarer Fingerabdruck (16 Hex-Zeichen).

    Er ist das, was eine Sicherung überhaupt prüfbar macht: ohne ihn weisst du
    nach Jahren nicht, ob der abgetippte Seed der richtige war.
    """
    import hashlib
    return hashlib.sha256(public_raw(key)).hexdigest()[:16]


def wrap(payload: bytes, key: Ed25519PrivateKey, key_id: str) -> dict:
    """Nutzdaten signieren und in den Umschlag legen."""
    if not key_id:
        raise SigningError("keyId fehlt — ohne sie kann der Client nach einem "
                           "Schlüsselwechsel nicht zuordnen")
    if key_id not in KEY_EPOCHS:
        raise SigningError(f"keyId {key_id!r} hat keine Epoche in KEY_EPOCHS — "
                           f"bekannt: {', '.join(sorted(KEY_EPOCHS))}")
    return {
        "envelopeVersion": ENVELOPE_VERSION,
        "alg": ALG,
        "keyId": key_id,
        "keyEpoch": KEY_EPOCHS[key_id],
        "payload": _b64(payload),
        "sig": _b64(key.sign(payload)),
    }


def unwrap(envelope: dict, public_keys: dict[str, Ed25519PublicKey],
           min_epoch: int = 0) -> bytes:
    """Umschlag prüfen → Nutzdaten. Wirft bei jedem Zweifel.

    `public_keys` bildet `keyId` → Schlüssel ab. Ein Umschlag mit unbekannter
    `keyId` ist ein Fehler, kein Grund zum Raten: genau so wirkt ein Widerruf.

    `min_epoch` ist die höchste Epoche, die der Aufrufer je gültig gesehen
    hat. Ein Umschlag darunter wird abgewiesen — auch mit gültiger Signatur.
    Das ist die Stelle, an der ein gestohlener Altschlüssel wirkungslos wird.
    """
    if envelope.get("alg") != ALG:
        raise SigningError(f"Unerwartetes Verfahren: {envelope.get('alg')!r}")
    if envelope.get("envelopeVersion") != ENVELOPE_VERSION:
        raise SigningError(f"Unbekannte Umschlagversion: "
                           f"{envelope.get('envelopeVersion')!r}")
    key_id = envelope.get("keyId")
    key = public_keys.get(key_id)
    if key is None:
        raise SigningError(f"Unbekannte keyId {key_id!r} — widerrufen oder gefälscht")

    epoch = envelope.get("keyEpoch")
    if not isinstance(epoch, int) or isinstance(epoch, bool):
        raise SigningError(f"keyEpoch fehlt oder ist keine Zahl: {epoch!r}")
    if epoch != KEY_EPOCHS.get(key_id):
        raise SigningError(f"keyEpoch {epoch} passt nicht zu keyId {key_id!r} "
                           f"(erwartet {KEY_EPOCHS.get(key_id)})")
    if epoch < min_epoch:
        raise SigningError(f"keyEpoch {epoch} liegt unter der bereits gesehenen "
                           f"Epoche {min_epoch} — widerrufener Schlüssel")

    payload = _unb64(envelope.get("payload", ""), "payload")
    signature = _unb64(envelope.get("sig", ""), "sig")
    try:
        key.verify(signature, payload)
    except InvalidSignature as exc:
        raise SigningError(f"Signatur passt nicht zu keyId {key_id!r}") from exc
    return payload


def serialize(envelope: dict) -> bytes:
    return json.dumps(envelope, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
