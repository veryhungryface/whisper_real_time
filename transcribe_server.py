#! python3.7

import argparse
import io
import socket
import struct
from tempfile import NamedTemporaryFile
from time import sleep

import human_readable
import speech_recognition as sr

import whisper


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, help="Server address", default='')
    parser.add_argument("--port", type=int, help="Server port number", default=12345)
    parser.add_argument("--model", default="large", help="Model to use",
                        choices=["tiny", "base", "small", "medium", "large"])
    parser.add_argument("--non_english", action='store_true',
                        help="Don't use the english model.")
    args = parser.parse_args()

    model = args.model
    if args.model != "large" and not args.non_english:
        model = model + ".en"
    audio_model = whisper.load_model(model)

    temp_file = NamedTemporaryFile().name

    # The last time a recording was retreived from the queue.
    # Current raw audio bytes.

    # Cue the user that we're ready to go.
    print("Model loaded.\n")

    sock = connection_coroutine()
    text = ''
    sock.send(None)
    data = sock.send(None)
    while True:
        try:
            # Use AudioData to convert the raw data to wav data.
            audio_data = sr.AudioData(data, 16000, 2)
            wav_data = io.BytesIO(audio_data.get_wav_data())

            # Write wav data to the temporary file as bytes.
            with open(temp_file, 'w+b') as f:
                f.write(wav_data.read())

            # Read the transcription.
            result = audio_model.transcribe(temp_file)
            text = result['text'].strip()
            print(text)
            try:
                data = sock.send(text)
            except StopIteration:
                break

            # Infinite loops are bad for processors, must sleep.
            sleep(0.25)
        except KeyboardInterrupt:
            break


def recv_exact(n, conn):
    data = b''
    while len(data) < n:
        data += conn.recv(n - len(data))
    return data


def connection_coroutine(host: str, port: int):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        s.listen(1)
        print("Listening")
        try:
            s.settimeout(5)
            conn, addr = s.accept()
            print('Connected by', addr)
            _ = yield
            with conn:
                while True:
                    length, = struct.unpack("l", recv_exact(8, conn))
                    if length == 0:  # Keepalive
                        print(".", end='')
                        continue
                    data_recv = recv_exact(length, conn)
                    print(f'[RECV] {human_readable.file_size(len(data_recv))} data')
                    text = yield data_recv
                    text = text.encode('utf8')
                    data = struct.pack("l", len(text)) + text
                    print(f'[SEND] {human_readable.file_size(len(data))} data')
                    conn.send(data)
        except KeyboardInterrupt:
            pass
        finally:
            s.close()


if __name__ == "__main__":
    main()
