"""A stand-in model server for end-to-end tests and demos: no account, no network.

It speaks the OpenAI-compatible API Ragolex uses, so pointing
EMBEDDING_BASE_URL and LLM_BASE_URL at it runs the whole app offline:

    python tools/fake_models.py --port 9999
    EMBEDDING_BASE_URL=http://127.0.0.1:9999/v1 LLM_BASE_URL=http://127.0.0.1:9999/v1 \\
        OPENAI_API_KEY=unused ANSWER_MIN_SCORE=0.05 uvicorn ragolex.main:app

- POST /v1/embeddings: a vector of the text's words, so texts sharing words
  are close; deterministic.
- POST /v1/chat/completions, streamed or not: an answer quoting the first
  sentence of the first source sharing a word with the question, cited as
  [n]; NO_ANSWER when none does. A follow-up is rewritten as itself.
- GET /health: 200 once it listens.

Its answers are not good ones; they are predictable, which is what a test needs.
"""

import argparse
import json
import re
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

QUESTION = re.compile(r"<question>\n(.*)\n</question>", re.DOTALL)
SOURCE = re.compile(r'<source id="(\d+)"[^>]*>\n(.*?)\n</source>', re.DOTALL)


def words(text: str) -> set[str]:
    # Short words (the, is, of) would make every text look alike.
    return {word for word in re.findall(r"\w+", text.lower()) if len(word) > 3}


def vector(text: str, dimensions: int) -> list[float]:
    values = [0.0] * dimensions
    values[0] = 0.01  # never all zeros, whose direction is undefined
    for word in re.findall(r"\w+", text.lower()):
        if len(word) > 3:
            values[1 + zlib.crc32(word.encode()) % (dimensions - 1)] += 1.0
    return values


def answer(messages: list[dict]) -> str:
    user = messages[-1]["content"]
    question = QUESTION.search(user)
    if question is None:
        return "NO_ANSWER"
    if "<conversation>" in user:  # rewriting a follow-up: keep it as it is
        return question.group(1)
    asked = words(question.group(1))
    for number, text in SOURCE.findall(user):
        if asked & words(text):
            return f"{text.strip().split('.')[0].strip()} [{number}]."
    return "NO_ANSWER"


class Handler(BaseHTTPRequestHandler):
    dimensions = 1536
    delay = 0.05  # between streamed pieces, so a client can see the answer being written

    def do_GET(self) -> None:
        if self.path == "/health":
            return self.reply(200, {"status": "ok"})
        self.reply(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path.endswith("/embeddings"):
            inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
            size = body.get("dimensions", self.dimensions)
            data = [{"object": "embedding", "index": index, "embedding": vector(text, size)}
                    for index, text in enumerate(inputs)]
            return self.reply(200, {"object": "list", "data": data, "model": body.get("model"),
                                    "usage": {"prompt_tokens": 1, "total_tokens": 1}})
        if self.path.endswith("/chat/completions"):
            text = answer(body["messages"])
            usage = {"prompt_tokens": 900, "completion_tokens": 30, "total_tokens": 930}
            if body.get("stream"):
                return self.stream(text, body, usage)
            return self.reply(200, {
                "id": "fake", "object": "chat.completion", "created": 0, "model": body.get("model"),
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": text}}],
                "usage": usage})
        self.reply(404, {"error": {"message": "not found"}})

    def stream(self, text: str, body: dict, usage: dict) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        base = {"id": "fake", "object": "chat.completion.chunk", "created": 0,
                "model": body.get("model")}
        for start in range(0, len(text), 8):
            piece = {**base, "choices": [{"index": 0, "finish_reason": None,
                                          "delta": {"content": text[start:start + 8]}}]}
            self.wfile.write(f"data: {json.dumps(piece)}\n\n".encode())
            self.wfile.flush()
            time.sleep(self.delay)
        if body.get("stream_options", {}).get("include_usage"):
            self.wfile.write(f"data: {json.dumps({**base, 'choices': [], 'usage': usage})}\n\n"
                             .encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def reply(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        pass  # quiet: test output stays readable


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--dimensions", type=int, default=1536,
                        help="vector length when a request does not ask for one")
    parser.add_argument("--delay", type=float, default=0.05,
                        help="seconds between the pieces of a streamed answer")
    args = parser.parse_args()
    Handler.dimensions, Handler.delay = args.dimensions, args.delay
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
