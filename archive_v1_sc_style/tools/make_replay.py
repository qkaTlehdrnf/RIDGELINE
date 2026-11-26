"""Embed a replay json into a standalone viewer page:  python tools/make_replay.py replay.json out.html"""
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
html = open(os.path.join(here, "viewer.html"), encoding="utf-8").read()
data = open(sys.argv[1], encoding="utf-8").read()
open(sys.argv[2], "w", encoding="utf-8").write(html.replace("/*REPLAY*/null/*END*/", data))
print("wrote", sys.argv[2], len(data) // 1024, "KB")
