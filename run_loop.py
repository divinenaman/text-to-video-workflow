import subprocess

filename = "app.py"
while True:
    p = subprocess.Popen("./venv/bin/python " + filename, shell=True).wait()

    if p != 0:
        continue
    else:
        break
