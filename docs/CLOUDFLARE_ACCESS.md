# Secure external access through Cloudflare Tunnel

The Academy can use `example.invalid` without opening an inbound port on
the router or exposing Proxmox. A Cloudflare Tunnel connector runs inside the
Academy services VM and makes an outbound-only connection to Cloudflare. The
only published origin is the Academy HTTPS service on local port 443.

This design deliberately does not publish Proxmox port 8006, SSH, PostgreSQL,
Docker, the learner bridge or any private IP range. Cloudflare Tunnel supports
WebSockets, so the embedded Guacamole terminal continues to use the same HTTPS
hostname as the rest of the Academy.

## Local preparation

The offline media includes the pinned amd64 Cloudflare connector package. Stage
it on the services VM without starting a tunnel:

```bash
sudo bash scripts/install-cloudflare-connector.sh /path/to/academy-media
```

The command verifies the package checksum, installs `cloudflared`, copies the
Academy's local CA to `/etc/cloudflared/local-ca.crt`, and leaves the connector
disabled. Confirm origin TLS before creating a tunnel:

```bash
curl --fail --cacert /opt/training-academy/secrets/local-ca.crt \
  --resolve academy.example.invalid:443:127.0.0.1 \
  https://academy.example.invalid/api/health
```

The VM needs outbound DNS, TCP 443 and TCP/UDP 7844 to Cloudflare. No inbound
firewall or NAT rule is required.

## Cloudflare configuration

In Cloudflare Zero Trust, create one remotely managed tunnel named
`training-academy`. Install its connector on the services VM using the one-time
tunnel token shown by Cloudflare. Store the token only in the root-owned
connector service configuration; never place it in Academy source, screenshots,
support logs or the deployment ZIP.

Save only the token value in a root-readable temporary file, then run:

```bash
sudo bash scripts/activate-cloudflare-connector.sh /root/tunnel-token.txt
sudo rm -f /root/tunnel-token.txt
```

The connector runs as an unprivileged local account with a locked-down systemd
service. The token file is readable only by root and that service account.

Create exactly one published application route:

| Setting | Value |
| --- | --- |
| Public hostname | `example.invalid` |
| Service type | HTTPS |
| Service URL | `https://127.0.0.1:443` |
| HTTP Host Header | `example.invalid` |
| Origin Server Name | `academy.example.invalid` |
| CA Pool | `/etc/cloudflared/local-ca.crt` |

Keep TLS verification enabled. Do not select **No TLS Verify**. The Origin Server
Name matches the existing Academy certificate while the CA Pool lets the
connector trust the Academy's private CA. Add a final catch-all 404 route if a
local configuration file is used.

Cloudflare creates the proxied DNS record for the public hostname. Do not create
an `A` record pointing to the home public IP. The tunnel hides the origin address
and does not require port forwarding.

## Academy and edge protections

Keep the Academy's own account login enabled. Use Cloudflare's managed security
rules and a rate limit for repeated requests to `/api/login`. Do not cache any
`/api/*` or `/console/*` response. The Academy already marks API and console
responses `no-store`, uses secure SameSite cookies and restricts its console
capabilities to the signed-in user and active lab session.

An optional Cloudflare Access policy adds a second sign-in layer, but it changes
the learner sign-in experience and requires an explicit list of allowed users or
identity providers. Do not enable it without an approved audience and recovery
administrator.

## Acceptance test

Test from a device that is not connected to the Academy LAN:

1. Open `https://example.invalid` and confirm a valid Cloudflare-served TLS
   certificate and the normal Academy sign-in page.
2. Sign in using a non-administrator test account.
3. Open an existing class and confirm an embedded slide PDF loads.
4. Start the Netlab, wait for Ready, and open the embedded terminal.
5. Run a short shell command, change focus away and back, and confirm input still
   works.
6. Start, check and finish one exercise; then end the lab and confirm its VM is
   deleted.
7. Confirm `https://example.invalid:8006`, SSH, database ports and private
   learner addresses are not reachable through the hostname.

## Rollback

Disable the tunnel connector service first, then remove the
`example.invalid` published route or its proxied DNS record in Cloudflare.
LAN access through `https://192.0.2.10` remains available. Remove the connector
token from the services VM if external access will not be restored. No Academy
database, class, account, lab template or learner result needs to be changed.

Use `sudo bash scripts/disable-cloudflare-connector.sh` to stop the local
connector and remove its stored token.

## Offline recovery note

The Academy itself and its lab images can operate without internet access.
External access through Cloudflare cannot: the services VM must reach Cloudflare
continuously. If internet access is removed, the public hostname stops working
while LAN access and local labs continue normally.
