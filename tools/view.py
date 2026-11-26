"""Open a replay in the WebGL viewer:  python tools/view.py runs/replays/world_s1.rlr [--port 8790] [--no-browser]

Serves tools/viewer_gl.html and the replay on localhost and opens the browser. (You can also open viewer_gl.html
directly and drop the .rlr file on it; this just saves the click.)"""
import http.server
import os
import sys
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"): print(__doc__); return
    rep = os.path.abspath(a[0]); port = int(a[a.index("--port") + 1]) if "--port" in a else 8790

    class H(http.server.SimpleHTTPRequestHandler):
        def translate_path(self, path):
            p = path.split("?")[0]
            return rep if p == "/replay.rlr" else os.path.join(HERE, "viewer_gl.html")

        def log_message(self, *x): pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    url = "http://127.0.0.1:%d/viewer_gl.html?src=/replay.rlr" % port
    print("viewer at", url, "(Ctrl+C to stop)")
    if "--no-browser" not in a: threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: pass


if __name__ == "__main__":
    main()
