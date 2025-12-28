import requests

url = "https://raw.githubusercontent.com/alphacep/vosk-recasepunc/master/vosk_recasepunc.py"
r = requests.get(url)

if r.status_code == 200:
    with open("vosk_recasepunc.py", "w", encoding='utf-8') as f:
        f.write(r.text)
    print("Successfully downloaded 'vosk_recasepunc.py'.")
else:
    print(f"Failed to download. Status code: {r.status_code}")