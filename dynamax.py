import asyncio
import re
import time
import threading
import tkinter as tk
from tkinter import ttk

RADIO_HOST = '192.168.0.30'
RADIO_PORT = 4992
AMP_HOST = '192.168.0.19'
AMP_PORT = 4626
MAX_POWER = 350
MIN_POWER = MAX_POWER - 20

class Dynamax:
    def __init__(self, update_ui, update_status):
        self.radio_seq = 0
        self.radio_power = None
        self.amp_power = None
        self.radio_state = None
        self.update_ui = update_ui
        self.update_status = update_status
        self.running = False

    async def connect_radio(self):
        try:
            self.radio_reader, self.radio_writer = await asyncio.open_connection(RADIO_HOST, RADIO_PORT)
            self.send_radio_command('sub tx all')
        except Exception as e:
            self.update_status(f"Error connecting to radio: {e}")

    async def connect_amp(self):
        try:
            self.amp_reader, self.amp_writer = await asyncio.open_connection(AMP_HOST, AMP_PORT)
        except Exception as e:
            self.update_status(f"Error connecting to amplifier: {e}")

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
                time.sleep(0.1)
            elif self.amp_power > MAX_POWER:
                self.radio_power -= 1
                self.send_radio_command(f'transmit set rfpower {self.radio_power}')
            self.update_ui(self.radio_power, self.amp_power)

    async def handle_radio_messages(self):
        previous_state = None
        while self.running:
            try:
                line = await self.radio_reader.readline()
                if line:
                    line = line.decode().strip()
                    print(line)

                    if 'freq=' in line:
                        match = re.search(r'freq=(\d+)', line)
                        if match:
                            freq = match.group(1)
                            global MAX_POWER
                            if freq.startswith('50'):
                                MAX_POWER = 500
                                MIN_POWER = MAX_POWER - 20
                                self.update_status(f"6m detected. Setting maximum power to {MAX_POWER}w.")
                            else:
                                MAX_POWER = 350
                                MIN_POWER = MAX_POWER - 20
                                self.update_status(f"HF detected. Setting maximum power to {MAX_POWER}w.")

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
                            if previous_state == "TRANSMITTING" and self.radio_state != "TRANSMITTING":
                                self.radio_power = max(10, self.radio_power - 4)
                                self.send_radio_command(f'transmit set rfpower {self.radio_power}')
                                self.update_ui(self.radio_power, self.amp_power)
                            previous_state = self.radio_state
            except Exception as e:
                self.update_status(f"Error in radio message handler: {e}")

    async def handle_amp_messages(self):
        while self.running:
            try:
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
            except Exception as e:
                self.update_status(f"Error in amplifier message handler: {e}")

    async def run(self):
        self.running = True
        try:
            await self.connect_radio()
            await self.connect_amp()
            tasks = [
                asyncio.create_task(self.handle_radio_messages()),
                asyncio.create_task(self.handle_amp_messages())
            ]
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.update_status(f"Unexpected error: {e}")
        finally:
            self.running = False

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

        self.root.attributes("-topmost", True)
        self.root.focus_force()

        self.status_label = tk.Label(root, text=f"HF detected. Setting maximum power to {MAX_POWER}w.", font=('Helvetica', 12))
        self.status_label.grid(row=0, column=0, columnspan=2, pady=10, padx=20)

        self.radio_pwr = tk.StringVar(value="Radio: 0 w")
        self.amp_pwr = tk.StringVar(value="Amp: 0 w")

        self.radio_pwr_label = tk.Label(root, textvariable=self.radio_pwr, font=('Helvetica', 12))
        self.radio_pwr_label.grid(row=1, column=0, columnspan=2, pady=5)

        self.radio_pwr_progress = ttk.Progressbar(root, orient="horizontal", length=300, mode="determinate", maximum=100)
        self.radio_pwr_progress.grid(row=2, column=0, columnspan=2, pady=5)

        self.amp_pwr_label = tk.Label(root, textvariable=self.amp_pwr, font=('Helvetica', 12))
        self.amp_pwr_label.grid(row=3, column=0, columnspan=2, pady=5)

        self.amp_pwr_progress = ttk.Progressbar(root, orient="horizontal", length=300, mode="determinate", maximum=400)
        self.amp_pwr_progress.grid(row=4, column=0, columnspan=2, pady=5)  # Top padding only

        # Add a spacer
        spacer = tk.Frame(root, height=30)  # Height of 30 for bottom padding
        spacer.grid(row=5, column=0, columnspan=2)


        self.loop = asyncio.get_event_loop()
        self.dynamax = Dynamax(self.update_ui, self.update_status)
        self.start()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def update_status(self, status_text):
        self.status_label.config(text=status_text)

    def update_ui(self, radio_pwr, amp_pwr):
        if radio_pwr is not None:
            self.radio_pwr.set(f"Radio: {radio_pwr} w")
            self.radio_pwr_progress['value'] = radio_pwr
        if amp_pwr is not None:
            self.amp_pwr.set(f"Amp: {amp_pwr} w")
            self.amp_pwr_progress['value'] = amp_pwr

    def start(self):
        threading.Thread(target=lambda: self.loop.run_until_complete(self.dynamax.run()), daemon=True).start()

    def stop(self):
        self.loop.call_soon_threadsafe(self.dynamax.stop)
        self.loop.stop()

    def on_closing(self):
        self.stop()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style()
    style.theme_use('alt')
    app = App(root)
    root.mainloop()
