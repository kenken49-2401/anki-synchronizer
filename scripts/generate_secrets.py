"""Create keys locally without printing them. Do not upload this output to chat/Git."""
import os
import secrets
from cryptography.fernet import Fernet

fd = os.open("generated-secrets.env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as output:
    output.write("DATA_ENCRYPTION_KEY=" + Fernet.generate_key().decode() + "\n")
    output.write("OAUTH_ENCRYPTION_KEY=" + Fernet.generate_key().decode() + "\n")
    output.write("JWT_SIGNING_KEY=" + secrets.token_urlsafe(48) + "\n")
print("Created generated-secrets.env. Keep the keys private and back up the data encryption key securely.")
