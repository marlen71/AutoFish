#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Eternal FishMod — релизный скрипт (semver + GitHub Release).

Использование:
    python scripts/release.py                 # патч (1.3.0 -> 1.3.1)
    python scripts/release.py minor           # минор (1.3.0 -> 1.4.0)
    python scripts/release.py major           # мажор (1.3.0 -> 2.0.0)
    python scripts/release.py patch --notes "Исправлен клик по «Использовать»"
    python scripts/release.py patch --dry-run # только показать, что будет сделано
    python scripts/release.py minor --no-push # локальный коммит+тег, без отправки на GitHub
    python scripts/release.py --zip-only      # просто собрать релизный zip (нужен CI)

Что делает (по порядку):
  1. читает версию из VERSION и сверяет с APP_VERSION в eternal_fishmod.py;
  2. поднимает её по semver;
  3. пишет новую версию в VERSION и в APP_VERSION (одна строка, regex-замена);
  4. добавляет в начало CHANGELOG.md датированную запись (текст — из --notes или заглушка);
  5. git add -A && git commit -m "release: vX.Y.Z";
  6. git tag -a vX.Y.Z;
  7. git push && git push origin vX.Y.Z;
  8. создаёт GitHub Release с прикреплённым архивом eternal_fishmod_vX.Y.Z.zip —
     через `gh` CLI (основной путь) либо через REST API по GITHUB_TOKEN (запасной).

Требования: git; для публикации релиза — установленный и авторизованный `gh`
(`gh auth login`) ИЛИ переменная окружения GITHUB_TOKEN (для REST-пути).
Без доступа к GitHub шаги 7-8 пропускаются с внятным сообщением: тег и коммита это не отменяет.
"""
import io
import os
import re
import sys
import json
import shutil
import argparse
import datetime
import subprocess
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VERSION_FILE = os.path.join(ROOT, "VERSION")
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
MAIN = os.path.join(ROOT, "eternal_fishmod.py")
RELEASE_NAME_RE = re.compile(r"^## \[(\d+)\.(\d+)\.(\d+)\]")

# В релизный архив попадает ТОЛЬКО то, чем реально пользуются: бот, лаунчер, файлы запуска,
# requirements и откалиброванные шаблоны. Всё остальное (tests/, scripts/release.py, .github/,
# CHANGELOG.md, .git*) остаётся в репозитории как исходники: распаковал — двойной клик — работает,
# без «лишней папки со скриптами». .bat/.vbs в архиве CRLF, потому что workflow собирает архив
# из checkout, где .gitattributes уже отработал.
INCLUDE_FILES = ["eternal_fishmod.py", "launch.py", "start.bat", "start_admin.bat", "start.vbs",
                 "requirements.txt", "README.md", "VERSION"]
INCLUDE_DIRS = [("templates", False), ("sounds", True), ("ai", False)]
EXCLUDE_EXT = {".pyc", ".log", ".tmp"}          # мусор; sounds/auto исключается отдельно
EXCLUDE_DIRS = {"auto", "__pycache__", ".git"}


# ----------------------------------------------------------------------------- вывод
def ok(msg):
    print("  \u2713 " + msg)


def warn(msg):
    print("  ! " + msg)


def err(msg, hint=""):
    print("  \u2717 " + msg)
    if hint:
        for ln in hint.splitlines():
            print("      " + ln)


def hdr(msg):
    print("")
    print("=== " + msg + " " + "=" * max(0, 66 - len(msg)))


# ----------------------------------------------------------------------------- git/gh
def run(cmd, capture=True, cwd=ROOT):
    """Возвращает (rc, stdout+stderr). Никаких исключений — всё решают вызывающие."""
    try:
        p = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE if capture else None,
                           stderr=subprocess.STDOUT if capture else None,
                           text=True, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "").strip()
    except FileNotFoundError:
        return 127, "command not found: %s" % (cmd[0] if cmd else "?")
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


def git(args, **kw):
    return run(["git"] + args, **kw)


def need_git():
    rc, out = git(["--version"])
    if rc != 0:
        err("git не найден в PATH.", "Установи Git: https://git-scm.com/download/win и перезапусти терминал.")
        sys.exit(2)
    rc, out = git(["rev-parse", "--is-inside-work-tree"])
    if rc != 0 or out.strip() != "true":
        err("Каталог %s не является git-репозиторием." % ROOT,
            "Инициализируй: git init && git remote add origin https://github.com/<user>/<repo>.git")
        sys.exit(2)


def repo_slug():
    rc, url = git(["remote", "get-url", "origin"])
    if rc != 0 or not url:
        return None, None
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", url.strip())
    if not m:
        return None, None
    return m.group(1), m.group(2)


def gh_available():
    rc, out = run(["gh", "--version"], capture=True)
    if rc != 0:
        return False, "gh CLI не установлен"
    rc, out = run(["gh", "auth", "status"])
    if rc != 0:
        return False, "gh не авторизован (выполни: gh auth login)"
    return True, "gh готов"


# ----------------------------------------------------------------------------- версия
def read_version_file():
    try:
        with io.open(VERSION_FILE, encoding="utf-8") as f:
            v = f.read().strip()
        if re.match(r"^\d+\.\d+\.\d+$", v):
            return v
        err("Файл VERSION повреждён (ожидалось MAJOR.MINOR.PATCH).", "Текущее содержимое: %r" % v)
        sys.exit(2)
    except FileNotFoundError:
        return None


def read_app_version():
    try:
        with io.open(MAIN, encoding="utf-8") as f:
            m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', f.read(), re.M)
        return m.group(1) if m else None
    except FileNotFoundError:
        return None


def bump(v, level):
    major, minor, patch = (int(x) for x in v.split("."))
    if level == "major":
        return "%d.0.0" % (major + 1)
    if level == "minor":
        return "%d.%d.0" % (major, minor + 1)
    return "%d.%d.%d" % (major, minor, patch + 1)


def write_version(new_v):
    with io.open(VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(new_v + "\n")
    with io.open(MAIN, encoding="utf-8") as f:
        src = f.read()
    src2, n = re.subn(r'^APP_VERSION\s*=\s*"[^"]*"', 'APP_VERSION = "%s"' % new_v, src, count=1, flags=re.M)
    if n != 1:
        err('В eternal_fishmod.py не найдена строка `APP_VERSION = "..."`.',
            'Добавь её вручную рядом с APP_NAME, иначе лог версии рассинхронизируется.')
        sys.exit(2)
    with io.open(MAIN, "w", encoding="utf-8") as f:
        f.write(src2)
    return n


def prepend_changelog(new_v, notes):
    date = datetime.date.today().isoformat()
    entry = "## [%s] - %s\n\n%s\n" % (new_v, date, (notes or "- Describe changes here / Опиши изменения").strip())
    try:
        with io.open(CHANGELOG, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = "# Changelog\n\nФормат — Keep a Changelog, версионирование — Semantic Versioning.\n\n"
    m = re.search(r"^## \[", text, re.M)
    if m:
        text = text[:m.start()] + entry + "\n" + text[m.start():]
    else:
        text = text.rstrip("\n") + "\n\n" + entry
    with io.open(CHANGELOG, "w", encoding="utf-8") as f:
        f.write(text)


# ----------------------------------------------------------------------------- архив
def build_zip(version, out_path=None):
    name = out_path or os.path.join(ROOT, "eternal_fishmod_v%s.zip" % version)
    top = "eternal_fishmod"
    tmp = os.path.join(ROOT, ".release_tmp", top)
    shutil.rmtree(os.path.join(ROOT, ".release_tmp"), ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    added = []
    for rel in INCLUDE_FILES:
        src = os.path.join(ROOT, rel)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(tmp, rel))
            added.append(rel)
        else:
            warn("в архив не попал %s (файла нет)" % rel)
    for rel, skip_auto in INCLUDE_DIRS:
        src = os.path.join(ROOT, rel)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(tmp, rel)
        os.makedirs(dst, exist_ok=True)
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not (skip_auto and d == "auto")]
            for fn in files:
                if os.path.splitext(fn)[1].lower() in EXCLUDE_EXT:
                    continue
                full = os.path.join(root, fn)
                relp = os.path.relpath(full, ROOT)
                out = os.path.join(tmp, relp)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                shutil.copy2(full, out)
                added.append(relp)
    zip_root = os.path.join(ROOT, ".release_tmp")
    if os.path.exists(name):
        os.remove(name)
    base = os.path.splitext(name)[0]
    made = shutil.make_archive(base, "zip", root_dir=zip_root, base_dir=top)
    shutil.rmtree(zip_root, ignore_errors=True)
    return made, added


# --------------------------------------------------------------------- ассеты релиза
def gh_asset_names(tag):
    """Реально прикреплённые к релизу файлы (gh может вернуть 0 и не прикрепить архив)."""
    rc, out = run(["gh", "release", "view", tag, "--json", "assets", "--jq", ".assets[].name"])
    if rc != 0:
        return []
    return [l.strip() for l in out.splitlines() if l.strip()]


def gh_upload_asset(tag, asset, tries=3):
    """Прикрепить zip к релизу с повторами и ПРОВЕРКОЙ.

    uploads.github.com — отдельный хост: он отдаёт кратковременные обрывы (EOF), а
    окружение без прямого доступа к нему (CI-песочницы, прокси) не отдаёт его вообще.
    Поэтому «rc == 0» вердиктом не считаю: смотрю, появился ли файл в списке ассетов.
    """
    if not asset or not os.path.exists(asset):
        return False
    name = os.path.basename(asset)
    last = ""
    for i in range(1, tries + 1):
        rc, out = run(["gh", "release", "upload", tag, asset, "--clobber"])
        last = (out or "").strip()
        if rc == 0 and name in gh_asset_names(tag):
            ok("архив %s прикреплён к релизу (%.1f КБ)"
               % (name, os.path.getsize(asset) / 1024.0))
            return True
        if i < tries:
            warn("архив не прикрепился (попытка %d/%d): %s — повторяю"
                 % (i, tries, last.splitlines()[-1][:160] if last else "?"))
            time.sleep(2 * i)
    err("архив так и не прикрепился.", last[:400])
    return False


def attach_hint(tag, version):
    """Что делать, если архив в релизе так и не появился."""
    owner, repo = _slug()
    print("  Как скачать без аттачмента:")
    if owner and owner != "?":
        print("    https://github.com/%s/%s/archive/%s.zip            (исходники тега = те же файлы)"
              % (owner, repo, tag))
    print("    gh release upload %s eternal_fishmod_v%s.zip --clobber   (с машины, где доступен"
          " uploads.github.com)" % (tag, version))
    print("    либо пуш/повтор тега: workflow Release build приложит архив сам")


# ----------------------------------------------------------------------------- релиз
def create_release_gh(tag, notes_file, asset, draft=False):
    """Создать/обновить релиз через gh CLI. Возвращает (опубликован, ссылка, архив_в_релизе).

    Архив намеренно довожу отдельной загрузкой: `gh release create <tag> ... file.zip`
    при обрыве загрузки ассета оставляет релиз либо без архива, либо вообще удалённым
    (черновик откатывается) — ровно это и было получено одним EOF'ом на практике.
    """
    ver = tag[1:] if tag.startswith("v") else tag
    cmd = ["gh", "release", "create", tag, "--title", tag, "--notes-file", notes_file]
    if draft:
        cmd.append("--draft")
    rc, out = run(cmd)
    if rc != 0 and "already exists" in out.lower():
        rc, out = run(["gh", "release", "edit", tag, "--title", tag, "--notes-file", notes_file])
    if rc != 0:
        return False, out, False
    asset_ok = gh_upload_asset(tag, asset)
    if asset and not asset_ok:
        attach_hint(tag, ver)
    url = "https://github.com/%s/%s/releases/tag/%s" % (_slug()[0], _slug()[1], tag)
    return True, (out.splitlines()[-1].strip() or url), asset_ok


def _slug():
    return repo_slug() or ("?", "?")


def create_release_rest(tag, notes, asset_path, token):
    owner, repo = _slug()
    api = "https://api.github.com"
    ver = tag[1:] if tag.startswith("v") else tag
    payload = json.dumps({"tag_name": tag, "name": tag, "body": notes,
                          "draft": False, "prerelease": False}).encode()
    req = urllib.request.Request(api + "/repos/%s/%s/releases" % (owner, repo), data=payload, method="POST",
                                 headers={"Authorization": "token " + token, "Content-Type": "application/json",
                                          "Accept": "application/vnd.github+json", "User-Agent": "efm-release"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code == 422:                      # релиз уже есть — просто дольём архив
            try:
                with urllib.request.urlopen(api + "/repos/%s/%s/releases/tags/%s" % (owner, repo, tag),
                                            headers={"Authorization": "token " + token,
                                                     "User-Agent": "efm-release"}, timeout=30) as r:
                    data = json.loads(r.read().decode("utf-8", "replace"))
            except Exception as e2:
                return False, "HTTP %s: %s (и загрузка существующего релиза не удалась: %s)" % (e.code, body[:200], e2)
        else:
            return False, "HTTP %s: %s" % (e.code, body[:300]), False
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e), False
    url = data.get("html_url", "")
    asset_ok = False
    up_url = (data.get("upload_url") or "").split("{")[0]
    if asset_path and os.path.exists(asset_path) and up_url:
        with open(asset_path, "rb") as f:
            blob = f.read()
        name = os.path.basename(asset_path)
        hdr_ = {"Authorization": "token " + token, "Content-Type": "application/zip",
                "Accept": "application/vnd.github+json", "User-Agent": "efm-release"}
        # uploads.github.com обязателен для ассетов; api.github.com отдаёт на них 404,
        # поэтому перебиваю хост только если uploads вообще недоступен (тогда хотя бы
        # попробую) и в любом случае сверяюсь со списком ассетов готового релиза.
        for cand in [up_url, up_url.replace("https://uploads.github.com", "https://api.github.com")]:
            if not cand:
                continue
            try:
                req2 = urllib.request.Request(cand + "?name=" + name, data=blob, method="POST", headers=hdr_)
                with urllib.request.urlopen(req2, timeout=120) as r2:
                    got = json.loads(r2.read().decode("utf-8", "replace"))
                if got.get("name") == name:
                    ok("архив %s (%.1f КБ) прикреплён" % (name, len(blob) / 1024.0))
                    asset_ok = True
                    break
            except Exception as e:
                warn("загрузка архива на %s: %s" % (cand.split("/")[2], "%s: %s" % (type(e).__name__, e)))
        if not asset_ok:
            rc, out = run(["gh", "release", "view", tag, "--json", "assets", "--jq", ".assets[].name"])
            asset_ok = rc == 0 and name in [l.strip() for l in out.splitlines() if l.strip()]
            if not asset_ok:
                attach_hint(tag, ver)
    return True, url, asset_ok


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Eternal FishMod: semver-бамп + GitHub Release",
                                 epilog="Уровень: patch (по умолчанию) | minor | major | X.Y.Z")
    ap.add_argument("level", nargs="?", default="patch", help="patch | minor | major | явная версия 1.2.3")
    ap.add_argument("--notes", default="", help="текст для CHANGELOG/описания релиза")
    ap.add_argument("--dry-run", action="store_true", help="ничего не менять и не отправлять")
    ap.add_argument("--no-push", action="store_true", help="коммит и тег локально, без push/релиза")
    ap.add_argument("--no-asset", action="store_true", help="не собирать zip-архив для релиза")
    ap.add_argument("--method", choices=["auto", "gh", "rest"], default="auto", help="как создавать релиз")
    ap.add_argument("--yes", "-y", action="store_true", help="не спрашивать подтверждение при грязном дереве")
    ap.add_argument("--zip-only", action="store_true", help="только собрать архив (для CI)")
    ap.add_argument("--out", default="", help="куда положить архив (--zip-only)")
    ap.add_argument("--allow-empty", action="store_true", help="создать релиз даже без изменений")
    ap.add_argument("--keep-artifacts", action="store_true", help="не удалять .release_notes.md и zip после запуска")
    ap.add_argument("--publish-only", action="store_true",
                    help="ничего не бампать и не коммитить: только архив + GitHub Release для текущей версии")
    args = ap.parse_args()

    hdr("Eternal FishMod — выпуск релиза")
    v_file = read_version_file()
    v_code = read_app_version()
    if v_file is None and v_code is None:
        err("Нет ни VERSION, ни APP_VERSION — непонятно, от какой версии считать.")
        sys.exit(2)
    cur = v_file or v_code
    ok("текущая версия: VERSION=%s, APP_VERSION=%s" % (v_file or "—", v_code or "—"))
    if v_file and v_code and v_file != v_code:
        warn("VERSION и APP_VERSION различаются (%s != %s) — синхронизируем на новой версии" % (v_file, v_code))

    if args.zip_only:
        version = args.level if re.match(r"^\d+\.\d+\.\d+$", args.level) else cur
        made, added = build_zip(version, args.out or None)
        ok("собран %s (%d файлов, %.1f КБ)" % (os.path.basename(made), len(added),
                                                os.path.getsize(made) / 1024.0))
        print(made)
        return 0

    if args.publish_only:
        new_v = cur
    elif re.match(r"^\d+\.\d+\.\d+$", args.level):
        new_v = args.level
    elif args.level in ("patch", "minor", "major"):
        new_v = bump(cur, args.level)
    else:
        err("непонятный уровень: %r" % args.level, "Можно: patch | minor | major | 1.2.3")
        return 2
    tag = "v" + new_v
    ok("новая версия: %s -> %s (тег %s)" % (cur, new_v, tag))

    need_git()
    rc, dirty = git(["status", "--porcelain"])
    dirty_lines = [l for l in dirty.splitlines() if l.strip()]
    if dirty_lines and args.dry_run:
        warn("несохранённых файлов: %d (в dry run ничего не меняем)" % len(dirty_lines))
    elif dirty_lines and not args.yes:
        warn("в репозитории есть несохранённые изменения (%d файл(ов)) — они попадут в релизный коммит:" % len(dirty_lines))
        for l in dirty_lines[:12]:
            print("      " + l)
        if len(dirty_lines) > 12:
            print("      ... и ещё %d" % (len(dirty_lines) - 12))
        try:
            ans = input("  Продолжить? [y/N] ").strip().lower()
        except Exception:
            ans = ""
        if ans not in ("y", "yes", "да"):
            err("Отменено. Закоммить правки (или добавь --yes), затем повтори выпуск.")
            return 3
    if not dirty_lines and not args.allow_empty:
        warn("дерево чистое: кроме VERSION/CHANGELOG менять нечего (--allow-empty создаст пустой релиз).")

    if args.dry_run:
        hdr("DRY RUN — ничего не меняем")
        print("  будет сделано: VERSION=%s, APP_VERSION=%s, тег %s, коммит 'release: %s', push, GitHub Release"
              % (new_v, new_v, tag, tag))
        return 0

    if args.publish_only:
        hdr("1..3 пропущены (--publish-only): версия, CHANGELOG, коммит и тег не трогаем")
        rc, out = git(["rev-parse", "-q", "--verify", "refs/tags/" + tag])
        notes_file = os.path.join(ROOT, ".release_notes.md")
        with io.open(notes_file, "w", encoding="utf-8") as f:
            f.write(render_release_notes(new_v))
        asset = None if args.no_asset else build_zip(new_v)[0]
        url = None
        if args.no_push:
            cleanup(notes_file, asset, args, keep=True)
            summary(tag, new_v, None, pushed=False)
            return 0
        owner, repo = _slug()
        gh_ok, gh_msg = gh_available()
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        method = args.method if args.method != "auto" else ("gh" if gh_ok else ("rest" if token else "none"))
        asset_ok = False
        if method == "gh":
            done, info, asset_ok = create_release_gh(tag, notes_file, asset)
            url = info if done else None
            if not done:
                err("gh release create не удался.", info)
        if url is None and token and owner:
            done, info, ok2 = create_release_rest(tag, io.open(notes_file, encoding="utf-8").read(), asset, token)
            url = info if done else None
            asset_ok = asset_ok or ok2
            if not done:
                err("REST-релиз не создан.", info)
        if url is None:
            warn("GitHub Release НЕ создан: нужен авторизованный gh (gh auth login) или GITHUB_TOKEN.")
        cleanup(notes_file, asset, args, keep=(url is None), drop_asset=bool(asset_ok))
        summary(tag, new_v, url, pushed=True,
                asset_ok=(None if args.no_asset else asset_ok))
        return 0 if url else 6

    hdr("1. Версия и CHANGELOG")
    write_version(new_v)
    ok("VERSION и APP_VERSION := %s" % new_v)
    notes = args.notes
    if not notes:
        rc, msg = git(["log", "-1", "--pretty=%s"])
        notes = "- Describe changes here / Опиши изменения"
        if msg:
            notes += "\n\nПоследний коммит перед релизом: `%s`" % msg
    prepend_changelog(new_v, notes)
    ok("CHANGELOG.md дополнен записью [%s]" % new_v)

    asset = None
    if not args.no_asset:
        hdr("2. Архив для релиза")
        asset, added = build_zip(new_v)
        ok("%s — %d файлов, %.1f КБ" % (os.path.basename(asset), len(added), os.path.getsize(asset) / 1024.0))

    hdr("3. Коммит и тег")
    rc, out = git(["add", "-A"])
    if rc != 0:
        err("git add не удался", out)
        return 4
    rc, out = git(["commit", "-m", "release: %s" % tag])
    if rc != 0:
        if "nothing to commit" in out:
            warn("изменений нет — пропускаю коммит")
        else:
            err("git commit не удался", out)
            return 4
    else:
        ok("коммит создан: release: %s" % tag)
    rc, out = git(["rev-parse", "-q", "--verify", "refs/tags/" + tag])
    if rc == 0:
        err("тег %s уже существует." % tag,
            "Удали его, если это ошибка:  git tag -d %s && git push origin :refs/tags/%s" % (tag, tag))
        return 5
    rc, out = git(["tag", "-a", tag, "-m", tag])
    if rc != 0:
        err("не удалось создать тег", out)
        return 5
    ok("тег %s создан (annotated)" % tag)

    notes_file = os.path.join(ROOT, ".release_notes.md")
    with io.open(notes_file, "w", encoding="utf-8") as f:
        f.write(render_release_notes(new_v))

    if args.no_push:
        hdr("4. Публикация (пропущена: --no-push)")
        print("  вручную:  git push && git push origin %s" % tag)
        print("            gh release create %s --title %s --notes-file .release_notes.md%s"
              % (tag, tag, (" " + asset) if asset else ""))
        cleanup(notes_file, asset, args)
        summary(tag, new_v, None, pushed=False)
        return 0

    hdr("4. Отправка в origin")
    rc, branch_out = git(["rev-parse", "--abbrev-ref", "HEAD"])
    branch = (branch_out or "main").strip()
    rc, out = git(["push", "origin", branch])
    pushed = rc == 0
    if not pushed:
        err("git push не удался.", out + "\nЧастые причины: нет сети, нет прав на push, ветка отстаёт "
                                          "(сделай git pull --rebase), защищённая ветка.")
    else:
        ok("коммит отправлен в origin/%s" % branch)
    rc, out = git(["push", "origin", tag])
    if rc != 0:
        err("не удалось отправить тег %s." % tag, out)
    else:
        ok("тег %s отправлен" % tag)

    hdr("5. GitHub Release")
    url = None
    asset_ok = False
    method = args.method
    gh_ok, gh_msg = gh_available()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if method == "auto":
        method = "gh" if gh_ok else ("rest" if token else "none")
    if method == "gh":
        ok("способ: gh CLI (%s)" % gh_msg)
        done, info, asset_ok = create_release_gh(tag, notes_file, asset)
        if done:
            url = info
        else:
            url = None
            err("gh release create не удался.", info)
            method = "rest" if token else "none"
    if method == "rest" and url is None:
        owner, repo = _slug()
        if not owner:
            warn("не могу определить владельца/имя репозитория из remote origin — REST-путь пропущен.")
            method = "none"
        elif not token:
            warn("REST-путь требует GITHUB_TOKEN (или поставь gh и выполни gh auth login) — релиз не создан.")
            method = "none"
        else:
            ok("способ: GitHub REST API (GITHUB_TOKEN)")
            done, info, ok2 = create_release_rest(tag, open(notes_file, encoding="utf-8").read(), asset, token)
            if done:
                url, asset_ok = info, ok2
            else:
                err("не удалось создать релиз через REST.", info)
                method = "none"
    if url is None:
        warn("GitHub Release НЕ создан (коммит и тег %s при этом на месте)." % tag)
        print("      проще всего — gh CLI:")
        print("          winget install GitHub.cli      (или https://cli.github.com)")
        print("          gh auth login")
        print("          gh release create %s --title %s --notes-file %s%s"
              % (tag, tag, os.path.basename(notes_file), (" " + asset) if asset else ""))
        print("      или через REST (нужен PAT со scope repo):")
        print("          set GITHUB_TOKEN=**** && python scripts/release.py publish-only %s" % new_v)
        method = "none"
    cleanup(notes_file, asset, args, keep=(url is None), drop_asset=bool(asset_ok))
    summary(tag, new_v, url, pushed=pushed,
            asset_ok=(None if args.no_asset else asset_ok))
    return 0 if (pushed and url) or args.no_push else 6


def render_release_notes(new_v):
    """Вырезает из CHANGELOG.md секцию новой версии — она и пойдёт в описание релиза."""
    try:
        with io.open(CHANGELOG, encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return "Eternal FishMod v%s" % new_v
    m = re.search(r"^## \[%s\].*?(?=^## \[|\Z)" % re.escape(new_v), text, re.S | re.M)
    body = m.group(0).strip() if m else "Eternal FishMod v%s" % new_v
    owner, repo = _slug()
    extra = ["", "### Как запустить", "",
             "Распакуй архив в любую папку и дважды кликни `start.bat` (или `python launch.py`) — "
             "лаунчер проверит Python, сам поставит зависимости и попросит права администратора.", ""]
    if owner and owner != "?":
        extra += ["### Скачать",
                  "- `eternal_fishmod_v%s.zip` — собранный архив (в аттачментах этого релиза)" % new_v,
                  "- [Исходники тега v%s (zip)](https://github.com/%s/%s/archive/refs/tags/v%s.zip) — "
                  "то же самое, если аттачмент недоступен" % (new_v, owner, repo, new_v), ""]
    return body + "\n" + "\n".join(extra) + "\n"


def cleanup(notes_file, asset, args, keep=False, drop_asset=False):
    if args.keep_artifacts or keep:
        if keep:
            warn("файл описания релиза оставлен: %s" % notes_file)
        return
    try:
        os.remove(notes_file)
    except Exception:
        pass
    if drop_asset and asset:          # архив уже в релизе — локальную копию не плодим
        try:
            os.remove(asset)
        except Exception:
            pass


def summary(tag, new_v, url, pushed=True, asset_ok=None):
    hdr("ИТОГ")
    print("  версия:      %s" % new_v)
    print("  тег:         %s" % tag)
    print("  push:        %s" % ("ok" if pushed else "НЕ выполнен — изменения только локально"))
    print("  CHANGELOG:   %s" % os.path.relpath(CHANGELOG, ROOT))
    if url:
        print("  релиз:       %s" % url)
    else:
        print("  релиз:       не создан (см. подсказки выше)")
    if asset_ok is None:
        print("  архив:       не собирался (--no-asset); приложит workflow Release build по тегу")
    elif asset_ok:
        print("  архив:       прикреплён к релизу")
    else:
        print("  архив:       НЕ прикреплён (см. подсказку выше; качай исходники тега)")
    print("")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Прервано пользователем.")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        print("\n  Внутренняя ошибка релизного скрипта: %s: %s" % (type(e).__name__, e))
        print("  Запусти с --dry-run, чтобы посмотреть план без изменений; подробности — `git status`.")
        if "-v" in sys.argv or "--verbose" in sys.argv:
            import traceback
            traceback.print_exc()
        sys.exit(1)
