"""Actual stdio MCP negotiation and tool calls using the official client."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from sonovect.mcp_server import create_server


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer protocol-test-secret":
            self.send_error(401)
            return
        if "format=srt" in self.path:
            content = b"1\n00:00:00,000 --> 00:00:00,500\nHello\n"
        else:
            value = ([{"key": "audio_0000", "text": "Hello", "timestamp": [[0, 500]]}]
                     if "/result" in self.path else {"api_version": "v1", "backend": "funasr"})
            content = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(content)


class MCPTests(unittest.TestCase):
    def test_official_stdio_initialize_list_and_structured_result(self):
        http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        async def check():
            params = StdioServerParameters(command=sys.executable, args=["-m", "sonovect.mcp_server"],
                cwd=str(Path(__file__).parents[1]), env={**os.environ,
                    "SONOVECT_TOKEN": "protocol-test-secret",
                    "SONOVECT_URL": f"http://127.0.0.1:{http.server_port}"})
            async with stdio_client(params) as streams:
                async with ClientSession(*streams) as session:
                    info = await session.initialize()
                    self.assertEqual(info.server_info.name, "sonovect")
                    listing = await session.list_tools()
                    names = {tool.name for tool in listing.tools}
                    self.assertEqual(names, {"sonovect_capabilities", "sonovect_submit", "sonovect_status", "sonovect_result", "sonovect_cancel", "sonovect_retry"})
                    for tool in listing.tools:
                        self.assertIsNotNone(tool.output_schema)
                    result = await session.call_tool("sonovect_result", {"job_id": "a" * 32})
                    self.assertFalse(result.is_error)
                    self.assertEqual(result.structured_content["data"], [{"key": "audio_0000", "text": "Hello", "timestamp": [[0, 500]]}])
                    subtitle = await session.call_tool("sonovect_result", {"job_id": "a" * 32, "format": "srt"})
                    self.assertEqual(subtitle.structured_content["data"], "1\n00:00:00,000 --> 00:00:00,500\nHello\n")
                    invalid = await session.call_tool("sonovect_result", {"job_id": "a" * 32, "layer": "analysis", "format": "srt"})
                    self.assertTrue(invalid.is_error)
                    bad = await session.call_tool("sonovect_submit", {"paths": ["/unconfigured/audio.wav"]})
                    self.assertTrue(bad.is_error)
        try:
            asyncio.run(check())
        finally:
            http.shutdown()
            http.server_close()
            thread.join()

    def test_input_root_rejects_symlinks_outside_operator_scope(self):
        async def check(root):
            server = create_server(client=object())
            with patch.dict(os.environ, {"SONOVECT_MCP_INPUT_ROOT": str(root / "allowed")}):
                from mcp.server.mcpserver.exceptions import ToolError
                with self.assertRaises(ToolError):
                    await server.call_tool("sonovect_submit", {"paths": [str(root / "allowed" / "link.wav")]})
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "allowed").mkdir()
            (root / "outside.wav").write_bytes(b"audio")
            (root / "allowed" / "link.wav").symlink_to(root / "outside.wav")
            asyncio.run(check(root))

    def test_submit_uses_shared_track_option_without_coercing_boolean_strings(self):
        class Service:
            def request(self, method, path):
                from types import SimpleNamespace
                return SimpleNamespace(json=lambda: {"max_files": 16})
            def submit(self, paths, options, key):
                return {"selected": options.model_dump()}
        async def check(root):
            server = create_server(client=Service())
            with patch.dict(os.environ, {"SONOVECT_MCP_INPUT_ROOT": str(root)}):
                arguments = {"paths": [str(root / "input.mp4")], "audio_track": 1, "speakers": False}
                value = await server.call_tool("sonovect_submit", arguments)
                self.assertEqual(value.structured_content["selected"]["audio_track"], 1)
                from mcp.server.mcpserver.exceptions import ToolError
                with self.assertRaises(ToolError):
                    await server.call_tool("sonovect_submit", {**arguments, "speakers": "false"})
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input.mp4").write_bytes(b"media")
            asyncio.run(check(root))


if __name__ == "__main__":
    unittest.main()
