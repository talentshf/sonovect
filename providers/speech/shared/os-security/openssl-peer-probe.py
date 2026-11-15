"""Check connected UDP peer detection without sending any network traffic."""
import ctypes
import json
import socket


def probe():
    library = ctypes.CDLL('libcrypto.so.3')
    pointer = ctypes.c_void_p
    library.BIO_new_dgram.argtypes = [ctypes.c_int, ctypes.c_int]
    library.BIO_new_dgram.restype = pointer
    library.BIO_ADDR_new.restype = pointer
    library.BIO_ADDR_family.argtypes = [pointer]
    library.BIO_ADDR_rawaddress.argtypes = [pointer, pointer, ctypes.POINTER(ctypes.c_size_t)]
    library.BIO_ctrl.argtypes = [pointer, ctypes.c_int, ctypes.c_long, pointer]
    library.BIO_ctrl.restype = ctypes.c_long
    library.BIO_free.argtypes = [pointer]
    library.BIO_ADDR_free.argtypes = [pointer]
    results = {}
    for family, host in ((socket.AF_INET, '127.0.0.1'), (socket.AF_INET6, '::1')):
        with socket.socket(family, socket.SOCK_DGRAM) as server, socket.socket(family, socket.SOCK_DGRAM) as client:
            server.bind((host, 0))
            client.connect(server.getsockname())
            bio, address = library.BIO_new_dgram(client.fileno(), 0), library.BIO_ADDR_new()
            if not bio or not address:
                raise RuntimeError('OpenSSL peer probe allocation failed')
            try:
                raw = ctypes.create_string_buffer(16)
                size = ctypes.c_size_t(len(raw))
                # Force automatic detection rather than a previously cached peer.
                if library.BIO_ctrl(bio, 44, 0, address) <= 0:
                    raise RuntimeError('OpenSSL peer reset failed')
                # Public BIO_CTRL_DGRAM_DETECT_PEER_ADDR in OpenSSL 3.5 bio.h.
                detected = library.BIO_ctrl(bio, 93, 0, address)
                read = library.BIO_ADDR_rawaddress(address, raw, ctypes.byref(size))
                results[host] = bool(detected > 0 and read == 1
                    and library.BIO_ADDR_family(address) == family
                    and raw.raw[:size.value] == socket.inet_pton(family, host))
            finally:
                library.BIO_ADDR_free(address)
                library.BIO_free(bio)
    return results


if __name__ == '__main__':
    results = probe()
    print(json.dumps(results))
    if not all(results.values()):
        raise SystemExit('OpenSSL connected peer address regression')
