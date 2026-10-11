"""Первичная установка сервера разведки одной командой (11.10.2026).

Запуск в консоли Aeza (только строчные буквы):  python3 bootstrap.py

Что делает:
  1) ставит библиотеки из requirements.txt;
  2) превращает папку в git-копию репозитория (если её скачали архивом),
     чтобы дальше обновляться обычным  git pull;
  3) ставит расписание (install_cron.py);
  4) запускает страницу настройки ключей (websetup.py).
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = "https://github.com/savely0711/farang-recon.git"


def run(cmd):
    print("→", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=BASE).returncode


def main():
    run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt",
         "--break-system-packages"])
    if not os.path.isdir(os.path.join(BASE, ".git")):
        run(["git", "init", "-q"])
        run(["git", "remote", "add", "origin", REPO])
        run(["git", "fetch", "-q", "origin"])
        run(["git", "reset", "-q", "--hard", "origin/main"])
        run(["git", "branch", "-q", "--set-upstream-to=origin/main"])
    run(["git", "pull", "-q"])
    run([sys.executable, "install_cron.py"])
    print("\nУстановка закончена. Запускаю страницу настройки ключей…", flush=True)
    os.execv(sys.executable, [sys.executable, "-u", os.path.join(BASE, "websetup.py")])


if __name__ == "__main__":
    main()
