# Rate limits

Rate limits govern how many requests a client may issue per minute. A 429
response means the rate limit was exceeded and the client should back off
before retrying. There is no separate throttling layer -- 429 is the only
signal a caller needs to watch for.
