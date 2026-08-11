# SERVER_SETUP.md — Laptop se Cloud (Oracle Free VM) tak

Isko follow karne ke baad: tum sirf Google Drive ke `staticurdureels` folder me
video daaloge, aur baaki **sab kuch** (Drive se download, schedule, publish,
token refresh) khud server pe hoga — laptop off ho, phone off ho, farak nahi
padega.

---

## Part A — Oracle Cloud account aur VM banana

1. https://signup.oraclecloud.com pe jaao, "Always Free" tier ke liye sign up
   karo. Credit card verification ke liye maangega, lekin Always Free
   resources pe kabhi charge nahi hota.
2. Console me: **Compute → Instances → Create Instance**
3. Image: **Ubuntu 22.04**, Shape: **VM.Standard.A1.Flex (Ampere, Always
   Free)** — 1 OCPU / 6GB RAM tak free hai, ye kaafi hai isके liye.
   (Agar A1 "out of capacity" error de — kabhi-kabhi deta hai — thodi der
   baad retry karo, ya region badal kar dekho.)
4. SSH keys: "Generate a key pair" choose karo, **private key file download
   kar lo** (`.pem` / `.key` file) — isी se VM me login hoga.
5. Create dabao. 1-2 min me VM ready ho jaayega — iska **Public IP address**
   note kar lo (yahi baar-baar use hoga).

## Part B — Firewall (Security List) me ports kholna

1. VM ke details page pe "Subnet" link pe click karo → **Security Lists** →
   default list kholo → **Add Ingress Rules**
2. Do rules add karo:
   - Source: `0.0.0.0/0`, Destination Port: `80` (HTTP, Caddy ke certificate
     ke liye zaroori)
   - Source: `0.0.0.0/0`, Destination Port: `443` (HTTPS — yahi asli traffic)
3. **Ubuntu ke andar bhi** firewall khud khulwana padega (Oracle VM me `iptables`
   pehle se strict hota hai) — Part C ke commands isko bhi handle karte hain.

## Part C — VM me connect karke basic setup

Windows se PuTTY ya (Windows 10/11 me built-in) `ssh` se connect karo:
```
ssh -i /path/to/downloaded-key.key ubuntu@<VM_PUBLIC_IP>
```

Connect hone ke baad, ye sab ek-ek karke chalao:
```bash
# System update + zaroori packages
sudo apt update && sudo apt install -y python3 python3-pip git ufw

# Local firewall (VM ke andar wala) — SSH + HTTP + HTTPS allow karo
sudo ufw allow 22
sudo ufw allow 80
sudo ufw allow 443
sudo ufw --force enable

# Caddy install (automatic HTTPS ke liye)
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy

# Ek dedicated user (security best practice — root se scripts nahi chalate)
sudo useradd -m -s /bin/bash staticurdureel
```

## Part D — Code server pe le jaana

Apne laptop se (jahan staticurdureel folder hai), server pe copy karo:
```
scp -i /path/to/downloaded-key.key -r D:\staticurdureel ubuntu@<VM_PUBLIC_IP>:/tmp/staticurdureel
```
Phir VM ke andar (SSH session me):
```bash
sudo mv /tmp/staticurdureel /opt/staticurdureel
sudo chown -R staticurdureel:staticurdureel /opt/staticurdureel
cd /opt/staticurdureel

# Python dependencies
sudo -u staticurdureel pip3 install --break-system-packages requests google-api-python-client google-auth google-auth-httplib2
```

`credentials.json` (Google Drive service account key) bhi isी tarah `scp` se
`/opt/staticurdureel/` me daal do.

## Part E — Config update (server ke liye)

`/opt/staticurdureel/user_config.json` banao (ya edit karo):
```json
{
  "reels_folder": "/opt/staticurdureel/reels",
  "drive_folder_id": "YOUR_DRIVE_FOLDER_ID",
  "hosting_mode": "direct",
  "public_base_url": "https://YOUR-IP-WITH-DASHES.nip.io",
  "max_reels_this_run": 1
}
```
`reels_folder` ab local Windows path nahi, VM ka path hai. Isko banao:
```bash
sudo -u staticurdureel mkdir -p /opt/staticurdureel/reels
```

## Part F — Caddy (HTTPS) configure karna

Apna VM IP dashes ke saath likho (jaise `123.45.67.89` → `123-45-67-89`),
`deploy/Caddyfile` ke andar `YOUR-VM-PUBLIC-IP-WITH-DASHES` ko replace karo,
phir:
```bash
sudo cp /opt/staticurdureel/deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
```
Same IP-with-dashes.nip.io URL `user_config.json` ke `public_base_url` me
bhi daal do (Part E me already dikhaya).

## Part G — systemd services enable karna (yahi asli automation hai)

```bash
sudo cp /opt/staticurdureel/deploy/fileserver.service /etc/systemd/system/
sudo cp /opt/staticurdureel/deploy/pipeline.service /etc/systemd/system/
sudo cp /opt/staticurdureel/deploy/pipeline.timer /etc/systemd/system/
sudo cp /opt/staticurdureel/deploy/token-refresh.service /etc/systemd/system/
sudo cp /opt/staticurdureel/deploy/token-refresh.timer /etc/systemd/system/

# token-refresh.service ke andar YOUR_APP_ID / YOUR_APP_SECRET fill karo:
sudo nano /etc/systemd/system/token-refresh.service

sudo systemctl daemon-reload
sudo systemctl enable --now fileserver
sudo systemctl enable --now pipeline.timer
sudo systemctl enable --now token-refresh.timer
```

Token ek baar manually daalo (long-lived wala jo pehle se bana rakha hai):
```bash
cd /opt/staticurdureel
sudo -u staticurdureel python3 -c "from token_store import write_token; write_token('YOUR_CURRENT_LONG_LIVED_TOKEN', 5184000)"
```

## Part H — Verify sab chal raha hai

```bash
sudo systemctl status fileserver        # active (running) dikhna chahiye
sudo systemctl list-timers              # pipeline.timer aur token-refresh.timer dikhenge
curl https://YOUR-IP-WITH-DASHES.nip.io/  # koi bhi test file dikhni chahiye (agar reels/ me kuch hai)

# Pipeline ko manually ek baar chala kar test karo:
cd /opt/staticurdureel
sudo -u staticurdureel python3 queue_manager.py
sudo -u staticurdureel python3 scheduler.py
sudo -u staticurdureel python3 publisher.py
```

Agar ye teeno bina error ke chal jaayein aur reel publish ho jaaye — **bas ho
gaya**. Ab tumhara kaam sirf itna hai:
1. Google Drive ke `staticurdureels` folder me video daalo
2. Bhool jaao — har 15 min me server khud check karega, sahi time pe khud
   publish karega, token khud renew hota rahega

## Logs kahan dekhein (kuch gadbad lage to)
```bash
journalctl -u pipeline.service -n 50 --no-pager
journalctl -u fileserver.service -n 50 --no-pager
journalctl -u token-refresh.service -n 50 --no-pager
```

## max_reels_this_run
Pehle test 1 reel se pass hone ke baad, `/opt/staticurdureel/user_config.json`
me `max_reels_this_run` ko `5`, phir `null` kar do (poore 100 reels ke liye).
