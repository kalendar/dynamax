import asyncio
import re
import threading
import tkinter as tk
from tkinter import ttk

RADIO_HOST = '192.168.0.30'
RADIO_PORT = 4992
AMP_HOST = '192.168.0.11'
AMP_PORT = 4626
TARGET_POWER = 350
MIN_POWER = 340
MAX_POWER = 350

class Dynamax:
    def __init__(self, update_ui):
        self.radio_seq = 0
        self.radio_power = None  # Will be read from the status broadcast
        self.amp_power = None  # Will be read from the status broadcast
        self.radio_state = None  # Will track the state of the radio
        self.update_ui = update_ui
        self.running = False

    async def connect_radio(self):
        self.radio_reader, self.radio_writer = await asyncio.open_connection(RADIO_HOST, RADIO_PORT)
        self.send_radio_command('sub tx all')

    async def connect_amp(self):
        self.amp_reader, self.amp_writer = await asyncio.open_connection(AMP_HOST, AMP_PORT)

    def send_radio_command(self, command):
        self.radio_seq += 1
        full_command = f'c{self.radio_seq}|{command}\n'
        print(f'Sending to radio: {full_command.strip()}')
        self.radio_writer.write(full_command.encode())
        asyncio.create_task(self.radio_writer.drain())

    def adjust_radio_power(self):
        if self.radio_state == "TRANSMITTING" and self.amp_power is not None and self.radio_power is not None:
            if self.amp_power < MIN_POWER:
                self.radio_power += 1
                self.send_radio_command(f'transmit set rfpower {self.radio_power}')
            elif self.amp_power > MAX_POWER:
                self.radio_power -= 1
                self.send_radio_command(f'transmit set rfpower {self.radio_power}')
            self.update_ui(self.radio_power, self.amp_power)

    async def handle_radio_messages(self):
        previous_state = None
        while self.running:
            line = await self.radio_reader.readline()
            if line:
                line = line.decode().strip()
                if 'rfpower' in line:
                    match = re.search(r'rfpower=(\d+)', line)
                    if match:
                        self.radio_power = int(match.group(1))
                        print(f'Initial radio power set to {self.radio_power}')
                        self.update_ui(self.radio_power, self.amp_power)
                elif 'state=' in line:
                    match = re.search(r'state=(\w+)', line)
                    if match:
                        self.radio_state = match.group(1)
                        print(f'Radio state: {self.radio_state}')
                        # When the radio stops transmitting, the amp power falls off and the radio power gets
                        # bumped up before the loop ends. Adjust down a few watts so the next TX doesn't start too hot.
                        if previous_state == "TRANSMITTING" and self.radio_state != "TRANSMITTING":
                            self.radio_power -= 4
                            self.send_radio_command(f'transmit set rfpower {self.radio_power}')
                            self.update_ui(self.radio_power, self.amp_power)
                        previous_state = self.radio_state

    async def handle_amp_messages(self):
        while self.running:
            line = await self.amp_reader.readline()
            if line:
                line = line.decode().strip()
                if 'amp::meter::Power::' in line:
                    match = re.search(r'amp::meter::Power::(\d+)', line)
                    if match:
                        self.amp_power = int(match.group(1))
                        print(f'Initial amp power set to {self.amp_power}')
                        self.update_ui(self.radio_power, self.amp_power)
                        if self.radio_state == "TRANSMITTING" and (self.amp_power < MIN_POWER or self.amp_power > MAX_POWER):
                            self.adjust_radio_power()

    async def run(self):
        self.running = True
        await self.connect_radio()
        await self.connect_amp()
        await asyncio.gather(
            self.handle_radio_messages(),
            self.handle_amp_messages(),
        )

    def stop(self):
        self.running = False
        if self.radio_writer:
            self.radio_writer.close()
        if self.amp_writer:
            self.amp_writer.close()

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Dynamax Control")

        self.info_label = tk.Label(root, text="Dynamically maximizing FT8 power!")
        self.info_label.pack(pady=10, padx=20)

        self.radio_pwr = tk.StringVar(value="Radio: 0 w")
        self.amp_pwr = tk.StringVar(value="Amp: 0 w")

        self.radio_pwr_label = tk.Label(root, textvariable=self.radio_pwr)
        self.radio_pwr_label.pack(pady=5)

        self.radio_pwr_progress = ttk.Progressbar(root, orient="horizontal", length=300, mode="determinate", maximum=100)
        self.radio_pwr_progress.pack(pady=5)

        self.amp_pwr_label = tk.Label(root, textvariable=self.amp_pwr)
        self.amp_pwr_label.pack(pady=5)

        self.amp_pwr_progress = ttk.Progressbar(root, orient="horizontal", length=300, mode="determinate", maximum=400)
        self.amp_pwr_progress.pack(pady=5)

        self.loop = asyncio.get_event_loop()
        self.dynamax = Dynamax(self.update_ui)
        self.start()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)  # Handle window close event

    def update_ui(self, radio_pwr, amp_pwr):
        if radio_pwr is not None:
            self.radio_pwr.set(f"Radio: {radio_pwr} w")
            self.radio_pwr_progress['value'] = radio_pwr
        if amp_pwr is not None:
            self.amp_pwr.set(f"Amp: {amp_pwr} w")
            self.amp_pwr_progress['value'] = amp_pwr

    def start(self):
        threading.Thread(target=self.loop.run_until_complete, args=(self.dynamax.run(),)).start()

    def stop(self):
        self.dynamax.stop()

    def on_closing(self):
        self.stop()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
