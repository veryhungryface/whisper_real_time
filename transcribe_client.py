#! python3.7
"""Microphone agent. Delegate heavy lifting to server, and do all the mic stuff"""

import argparse
import datetime
import io
import os
import queue
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from time import sleep

import speech_recognition as sr
import whisper


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, help="Server address", required=True)
    parser.add_argument("--port", type=int, help="Server port number", default=12345)
    parser.add_argument("--non_english", action='store_true',
                        help="Don't use the english model.")
    parser.add_argument("--energy_threshold", default=1000,
                        help="Energy level for mic to detect.", type=int)
    parser.add_argument("--record_timeout", default=2,
                        help="How real time the recording is in seconds.", type=float)
    parser.add_argument("--phrase_timeout", default=3,
                        help="How much empty space between recordings before we "
                             "consider it a new line in the transcription.", type=float)
    parser.add_argument("--logdir", type=Path, help="log directory to save", default='log')
    args = parser.parse_args()

    # The last time a recording was retreived from the queue.
    phrase_time = None
    phrase_timeout = args.phrase_timeout

    record_timeout = args.record_timeout
    transcription = ['']

    # The last time a recording was retreived from the queue.
    # Current raw audio bytes.
    current_sample = bytes()
    # Thread safe Queue for passing data from the threaded recording callback.
    data_queue = queue.Queue()

    # We use SpeechRecognizer to record our audio because it has a nice feauture where it can detect when speech ends.
    recorder = sr.Recognizer()
    recorder.energy_threshold = args.energy_threshold
    # Definitely do this, dynamic energy compensation lowers the energy threshold dramtically to a point where the SpeechRecognizer never stops recording.
    recorder.dynamic_energy_threshold = False

    source = sr.Microphone(sample_rate=16000)
    with source:
        recorder.adjust_for_ambient_noise(source)

    def record_callback(_, audio:sr.AudioData) -> None:
        """
        Threaded callback function to recieve audio data when recordings finish.
        audio: An AudioData containing the recorded bytes.
        """
        # Grab the raw bytes and push it into the thread safe queue.
        data = audio.get_raw_data()
        data_queue.put(data)

    # Create a background thread that will pass us raw audio bytes.
    # We could do this manually but SpeechRecognizer provides a nice helper.
    recorder.listen_in_background(source, record_callback, phrase_time_limit=record_timeout)

    # Cue the user that we're ready to go.
    print("Ready.\n")

    keepalive = KeepAlive(1)
    cnx = connection_coroutine(args.host, args.port)
    cnx.send(None)
    while True:
        try:
            # Pull raw recorded audio from the queue.
            if data_queue.empty():
                sleep(0.25)
                if keepalive.step():
                    # print(".", end="")
                    # sys.stdout.flush()
                    cnx.send(b'')
                continue

            # Concatenate our current audio data with the latest audio data.
            now = datetime.utcnow()
            phrase_complete = False
            if phrase_time and now - phrase_time > timedelta(seconds=phrase_timeout):
                # Save before reset, if specified
                if args.logdir is not None:
                    args.logdir.mkdir(exist_ok=True, parents=True)
                    audio_data = sr.AudioData(data, 16000, 2)
                    wav_data = io.BytesIO(audio_data.get_wav_data())
                    with (args.logdir / f"{now.isoformat()}.wav").open('w+b') as f:
                        f.write(wav_data.read())

                # Reset
                current_sample = bytes()
                phrase_complete = True
            phrase_time = now

            while not data_queue.empty():
                try:
                    data = data_queue.get(timeout=1)
                except :
                    print(".")
                    cnx.send(b'')
                    continue
                current_sample += data

            # Read the transcription.
            text = cnx.send(current_sample)
            keepalive.reset()

            # Otherwise edit the existing one.
            if phrase_complete:
                transcription.append(text)
            else:
                transcription[-1] = text

            # Clear the console to reprint the updated transcription.
            os.system('cls' if os.name=='nt' else 'clear')
            for line in transcription[-100:]:
                print(line)
            # Flush stdout.
            print('', end='', flush=True)

            # Infinite loops are bad for processors, must sleep.
            sleep(0.25)
        except KeyboardInterrupt:
            break

    print("\n\nTranscription:")
    for line in transcription:
        print(line)


class KeepAlive:
    def __init__(self, seconds: int):
        self.seconds = seconds
        self.last = datetime.utcnow()

    def reset(self):
        self.last = datetime.utcnow()

    def step(self):
        now = datetime.utcnow()
        ret = now - self.last < timedelta(seconds=self.seconds)
        if ret:
            self.last = now
        return ret


import socket
import struct


def recv_exact(n, conn):
    data = b''
    while len(data) < n:
        data += conn.recv(n - len(data))
    return data


@contextmanager
def connect(host: str, port: int, timeout_seconds: int = 60):
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.settimeout(timeout_seconds)
                s.connect((host, port))
                yield s
            except ConnectionRefusedError:
                print(f"Server is not available ({host}:{port}). Retry in 5 seconds.")
                sleep(5)
                continue
            s.close()
            break

    return


def connection_coroutine(host: str, port: int):
    with connect(host, port) as s:
        text = None

        while True:
            data = yield text
            # send
            try:
                s.send(struct.pack("l", len(data)) + data)
            except:
                raise RuntimeError("Gone while sending")

            if data == b'':  # Keepalive
                continue

            # receive
            try:
                length, = struct.unpack("l", recv_exact(8, s))
                text = recv_exact(length, s).decode('utf8')
            except:
                raise RuntimeError("Gone while receiving")


if __name__ == "__main__":
    main()