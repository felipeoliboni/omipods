#!/usr/bin/env python3
"""Reads battery status (left/right/case) from a Redmi Buds (5 Pro / 6 Lite
and likely other models sharing the same Xiaomi earbuds control protocol)
over the classic-Bluetooth RFCOMM control channel.

Protocol ported from Gadgetbridge's RedmiBuds5Pro support (AGPL-3.0,
https://codeberg.org/Freeyourgadget/Gadgetbridge) -- same packet framing and
SAFER+-based auth challenge/response cipher. Empirically confirmed to also
work, byte-for-byte, against the Redmi Buds 6 Lite.

Usage:
  redmi_buds_battery.py <mac-address> [--channel N] [--loop SECONDS]

Prints one JSON line per read, e.g.:
  {"connected": true, "left": {"level": 95, "charging": false},
   "right": {"level": 96, "charging": false}, "case": null}
  {"connected": false}

Read-only: performs the auth handshake and GET_DEVICE_INFO request only.
Never sends SET_CONFIG or any command that changes the earbuds' settings.
"""
import argparse
import json
import os
import socket
import struct
import sys
import time

HEADER = bytes([0xFE, 0xDC, 0xBA])
TRAILER = 0xEF

TYPE = {"PHONE_REQUEST": 0xC4, "RESPONSE": 0x04, "EARBUDS_REQUEST": 0xC0, "EARBUDS_NOTIFY": 0xC7}
TYPE_NAME = {v: k for k, v in TYPE.items()}

OPCODE = {
    "GET_DEVICE_INFO": 0x02, "ANC": 0x08, "GET_DEVICE_RUN_INFO": 0x09,
    "REPORT_STATUS": 0x0E, "AUTH_CHALLENGE": 0x50, "AUTH_CONFIRM": 0x51,
    "SET_CONFIG": 0xF2, "GET_CONFIG": 0xF3, "NOTIFY_CONFIG": 0xF4,
}
OPCODE_NAME = {v: k for k, v in OPCODE.items()}


def is_request(type_code):
    return (type_code & 0x40) != 0


def encode(type_code, opcode, seq, payload):
    size = 1 if is_request(type_code) else 2
    buf = bytearray(HEADER)
    buf.append(type_code)
    buf.append(opcode)
    buf += struct.pack(">H", len(payload) + size)
    if not is_request(type_code):
        buf.append(0x00)
    buf.append(seq & 0xFF)
    buf += payload
    buf.append(TRAILER)
    return bytes(buf)


def split_messages(buf):
    starts = [i for i in range(len(buf) - 2) if buf[i:i + 3] == HEADER]
    return [buf[s:(starts[i + 1] if i + 1 < len(starts) else len(buf))] for i, s in enumerate(starts)]


def decode(msg):
    type_code, opcode = msg[3], msg[4]
    req = is_request(type_code)
    payload_offset = 3 + (5 if req else 6)
    return {
        "type_name": TYPE_NAME.get(type_code, hex(type_code)),
        "opcode_name": OPCODE_NAME.get(opcode, hex(opcode)),
        "seq": msg[payload_offset - 1],
        "payload": msg[payload_offset:-1],
    }


# ---- SAFER+-variant auth cipher (ported from Gadgetbridge's Authentication.java) ----

SEQ_CONST = bytes([0x11, 0x22, 0x33, 0x33, 0x22, 0x11] * 2 + [0x11, 0x22, 0x33, 0x33])
COEFFICIENTS = [
    [2, 1, 1, 1, 4, 2, 1, 1, 2, 2, 4, 2, 4, 4, 16, 8],
    [2, 1, 1, 1, 4, 2, 1, 1, 1, 1, 2, 1, 2, 2, 8, 4],
    [1, 1, 4, 2, 2, 2, 4, 2, 16, 8, 4, 4, 2, 1, 1, 1],
    [1, 1, 4, 2, 1, 1, 2, 1, 8, 4, 2, 2, 2, 1, 1, 1],
    [16, 8, 2, 2, 4, 2, 4, 4, 1, 1, 4, 2, 1, 1, 2, 1],
    [8, 4, 1, 1, 2, 1, 2, 2, 1, 1, 4, 2, 1, 1, 2, 1],
    [2, 2, 4, 2, 4, 4, 16, 8, 2, 1, 1, 1, 4, 2, 1, 1],
    [1, 1, 2, 1, 2, 2, 8, 4, 2, 1, 1, 1, 4, 2, 1, 1],
    [4, 2, 4, 4, 16, 8, 2, 2, 1, 1, 2, 1, 1, 1, 4, 2],
    [2, 1, 2, 2, 8, 4, 1, 1, 1, 1, 2, 1, 1, 1, 4, 2],
    [4, 4, 16, 8, 1, 1, 2, 1, 4, 2, 1, 1, 4, 2, 2, 2],
    [2, 2, 8, 4, 1, 1, 2, 1, 4, 2, 1, 1, 2, 1, 1, 1],
    [1, 1, 2, 1, 1, 1, 4, 2, 4, 4, 16, 8, 2, 2, 4, 2],
    [1, 1, 2, 1, 1, 1, 4, 2, 2, 2, 8, 4, 1, 1, 2, 1],
    [4, 2, 1, 1, 2, 1, 1, 1, 4, 2, 2, 2, 16, 8, 4, 4],
    [4, 2, 1, 1, 2, 1, 1, 1, 2, 1, 1, 1, 8, 4, 2, 2],
]
PATTERN = 0x9999


def _bit_set(i):
    return ((1 << i) & PATTERN) != 0


class Authentication:
    def __init__(self):
        self.bias = [[0] * 16 for _ in range(16)]
        for i in range(16):
            for j in range(16):
                inner = pow(45, 17 * (i + 2) + (j + 1), 257)
                val = pow(45, inner, 257)
                self.bias[i][j] = 0 if val == 256 else val

        self.exp_tab = [0] * 256
        for i in range(256):
            val = pow(45, i, 257)
            self.exp_tab[i] = 0 if i == 128 else (val & 0xFF)

        self.log_tab = [0] * 256
        self.log_tab[0] = 128
        for i in range(1, 256):
            val = pow(45, i, 257)
            if val != 256:
                self.log_tab[val] = i & 0xFF

    def _key_schedule(self, key_init):
        key_init = bytearray(key_init)
        key_init[15] ^= 6
        register = list(key_init)
        xor = 0
        for b in register:
            xor ^= b
        register.append(xor)

        keys = [list(key_init)]
        for key_idx in range(1, 17):
            for i in range(17):
                v = register[i]
                register[i] = ((v << 3) | (v >> 5)) & 0xFF
            key_i = [(register[(key_idx + i) % 17] + self.bias[key_idx - 1][i]) & 0xFF for i in range(16)]
            keys.append(key_i)
        return keys

    def _encrypt(self, plaintext, keys):
        ct = list(plaintext)
        for rnd in range(8):
            if rnd == 2:
                for i in range(16):
                    ct[i] = (ct[i] ^ plaintext[i]) if _bit_set(i) else (ct[i] + plaintext[i]) & 0xFF
            for i in range(16):
                ct[i] = (ct[i] ^ keys[rnd * 2][i]) if _bit_set(i) else (ct[i] + keys[rnd * 2][i]) & 0xFF
            for i in range(16):
                ct[i] = self.exp_tab[ct[i]] if _bit_set(i) else self.log_tab[ct[i]]
            for i in range(16):
                ct[i] = (keys[rnd * 2 + 1][i] + ct[i]) & 0xFF if _bit_set(i) else keys[rnd * 2 + 1][i] ^ ct[i]
            ct_copy = list(ct)
            for i in range(16):
                ct[i] = sum(COEFFICIENTS[i][j] * ct_copy[j] for j in range(16)) & 0xFF
        for i in range(16):
            ct[i] = (keys[16][i] ^ ct[i]) if _bit_set(i) else (keys[16][i] + ct[i]) & 0xFF
        return bytes(ct)

    def compute_challenge_response(self, challenge):
        return self._encrypt(SEQ_CONST, self._key_schedule(challenge))


def parse_battery(byte_val):
    if byte_val == 0xFF:
        return None
    return {"level": byte_val & 0x7F, "charging": (byte_val & 0x80) != 0}


def parse_device_info(payload):
    i = 0
    battery = bytearray(3)
    while i + 1 < len(payload):
        length, index = payload[i], payload[i + 1]
        if index == 0x07 and i + 5 <= len(payload):
            battery[:] = payload[i + 2:i + 5]
        i += length + 1
    return {
        "left": parse_battery(battery[0]),
        "right": parse_battery(battery[1]),
        "case": parse_battery(battery[2]),
    }


def read_once(addr, channel, timeout=5.0):
    auth = Authentication()
    seq = 0
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    s.settimeout(timeout)
    try:
        s.connect((addr, channel))

        challenge = os.urandom(16)
        s.send(encode(TYPE["PHONE_REQUEST"], OPCODE["AUTH_CHALLENGE"], seq, bytes([0x01]) + challenge))
        seq += 1

        result = None
        sent_confirm = False
        requested_info = False
        deadline = time.time() + timeout

        while time.time() < deadline and result is None:
            try:
                data = s.recv(4096)
            except socket.timeout:
                break
            if not data:
                break
            for raw in split_messages(data):
                m = decode(raw)
                if m["opcode_name"] == "AUTH_CHALLENGE":
                    if m["type_name"] == "RESPONSE":
                        if not sent_confirm:
                            s.send(encode(TYPE["PHONE_REQUEST"], OPCODE["AUTH_CONFIRM"], seq, bytes([0x01, 0x00])))
                            seq += 1
                            sent_confirm = True
                    else:
                        resp = auth.compute_challenge_response(m["payload"][1:17])
                        s.send(encode(TYPE["RESPONSE"], OPCODE["AUTH_CHALLENGE"], m["seq"], bytes([0x01]) + resp))
                elif m["opcode_name"] == "AUTH_CONFIRM":
                    if m["type_name"] != "RESPONSE":
                        s.send(encode(TYPE["RESPONSE"], OPCODE["AUTH_CONFIRM"], m["seq"], bytes([0x01])))
                        if not requested_info:
                            s.send(encode(TYPE["PHONE_REQUEST"], OPCODE["GET_DEVICE_INFO"], seq,
                                           bytes([0xFF, 0xFF, 0xFF, 0xFF])))
                            seq += 1
                            requested_info = True
                elif m["opcode_name"] == "GET_DEVICE_INFO":
                    result = parse_device_info(m["payload"])
                elif m["opcode_name"] == "REPORT_STATUS":
                    s.send(encode(TYPE["RESPONSE"], OPCODE["REPORT_STATUS"], m["seq"], b""))

        return result
    finally:
        s.close()


def set_anc_mode(addr, channel, mode, timeout=8.0):
    """Sends the ambient-sound-control command (same opcode the Redmi Buds 5
    Pro uses: ANC opcode, sub-index 0x04). mode: 0=Off, 1=Transparency,
    2=Noise Cancellation. Returns True once the handshake completes and the
    command is sent (the earbuds don't ack this particular sub-command, so
    "sent" is the best confirmation available over this channel)."""
    auth = Authentication()
    seq = 0
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    s.settimeout(timeout)
    try:
        s.connect((addr, channel))

        challenge = os.urandom(16)
        s.send(encode(TYPE["PHONE_REQUEST"], OPCODE["AUTH_CHALLENGE"], seq, bytes([0x01]) + challenge))
        seq += 1

        sent_confirm = False
        authenticated = False
        deadline = time.time() + timeout

        while time.time() < deadline and not authenticated:
            try:
                data = s.recv(4096)
            except socket.timeout:
                break
            if not data:
                break
            for raw in split_messages(data):
                m = decode(raw)
                if m["opcode_name"] == "AUTH_CHALLENGE":
                    if m["type_name"] == "RESPONSE":
                        if not sent_confirm:
                            s.send(encode(TYPE["PHONE_REQUEST"], OPCODE["AUTH_CONFIRM"], seq, bytes([0x01, 0x00])))
                            seq += 1
                            sent_confirm = True
                    else:
                        resp = auth.compute_challenge_response(m["payload"][1:17])
                        s.send(encode(TYPE["RESPONSE"], OPCODE["AUTH_CHALLENGE"], m["seq"], bytes([0x01]) + resp))
                elif m["opcode_name"] == "AUTH_CONFIRM":
                    if m["type_name"] != "RESPONSE":
                        s.send(encode(TYPE["RESPONSE"], OPCODE["AUTH_CONFIRM"], m["seq"], bytes([0x01])))
                        authenticated = True

        if not authenticated:
            return False

        s.send(encode(TYPE["PHONE_REQUEST"], OPCODE["ANC"], seq, bytes([0x02, 0x04, mode & 0xFF])))
        seq += 1
        time.sleep(0.3)  # give the write a moment to go out before we close
        return True
    finally:
        s.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("address")
    p.add_argument("--channel", type=int, default=29)
    p.add_argument("--loop", type=float, default=0, help="seconds between reads; 0 = read once and exit")
    p.add_argument("--set-anc", type=int, choices=[0, 1, 2], default=None,
                    help="0=Off, 1=Transparency, 2=Noise Cancellation (one-shot, exits after sending)")
    args = p.parse_args()

    if args.set_anc is not None:
        try:
            ok = set_anc_mode(args.address, args.channel, args.set_anc)
        except OSError:
            ok = False
        print(json.dumps({"ok": ok, "mode": args.set_anc}), flush=True)
        return

    def emit():
        try:
            info = read_once(args.address, args.channel)
        except OSError:
            info = None
        out = {"connected": info is not None}
        if info is not None:
            out.update(info)
        print(json.dumps(out), flush=True)

    if args.loop <= 0:
        emit()
        return

    while True:
        emit()
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
