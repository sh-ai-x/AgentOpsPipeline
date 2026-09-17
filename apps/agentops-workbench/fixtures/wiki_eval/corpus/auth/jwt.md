# Auth

Requests are authenticated with a JSON Web Token (JWT) signed using
HS256. Set `AGENTOPS_JWT_SECRET` to a random secret at least 32 bytes
long and `AGENTOPS_JWT_EXPIRY_SECONDS` to control how long a minted token
stays valid before it expires.
