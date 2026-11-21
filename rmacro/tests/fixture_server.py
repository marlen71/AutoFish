"""Ephemeral local fixture for Windows GUI integration; never used in releases."""
import argparse
import importlib.util
from pathlib import Path

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rmacro_server", root / "server" / "server.py")
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)
parser = argparse.ArgumentParser()
parser.add_argument("--db", required=True)
parser.add_argument("--ready", required=True)
args = parser.parse_args()
db = srv.Database(args.db)
db.init_admin("fixture_admin", "fixture-admin-password")
user = db.create_user("fixture_admin", "fixture_user", "fixture-user-password")
db.change_user("fixture_admin", user["uid"], "grant", {"product": "rmfish", "seconds": 2 * 86400})
server = srv.Server(("127.0.0.1", 0), db)
Path(args.ready).write_text(str(server.server_address[1]), encoding="ascii")
try:
    server.serve_forever(poll_interval=0.2)
finally:
    server.server_close()
