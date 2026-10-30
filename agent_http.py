"""Small local JSON transport shared by the chart agent services."""
import json
import logging
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

def post_json(url, payload, timeout=45):
    request = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = json.load(error).get("error", str(error))
        except (ValueError, OSError):
            detail = str(error)
        raise ValueError(str(detail)) from error
    except urllib.error.URLError as error:
        raise ValueError(f"Agent service unavailable at {url}: {error.reason}") from error
    except (ConnectionError, TimeoutError, OSError) as error:
        raise ValueError(f"Agent service closed the connection at {url}; check the Agent log") from error


class JSONHandler(BaseHTTPRequestHandler):
    max_body = 300_000

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > self.max_body:
            raise ValueError("Request body too large or missing")
        result = json.loads(self.rfile.read(length))
        if not isinstance(result, dict):
            raise ValueError("Request body must be a JSON object")
        return result

    def send_json(self, result, status=200):
        body = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            self.send_json(self.route(self.read_json()))
        except (ValueError, SyntaxError, KeyError) as error:
            self.send_json({"error": str(error)}, 400)
        except Exception:
            logging.exception('Agent request failed unexpectedly')
            self.send_json({"error": "Agent encountered an internal error; check the Agent log"}, 500)

    def log_message(self, fmt, *args):
        print("%s %s" % (self.address_string(), fmt % args))
