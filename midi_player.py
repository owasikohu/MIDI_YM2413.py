import os
import time
import math
import board
import digitalio
import adafruit_midi_parser

# -----------------
# YM2413のピン設定と基本関数
# -----------------
pin_map = {
    'D7': board.GP0, 'D6': board.GP1, 'D5': board.GP2, 'D4': board.GP3,
    'D3': board.GP4, 'D2': board.GP5, 'D1': board.GP10, 'D0': board.GP11,
    'IC': board.GP12, 'CS': board.GP13, 'WE': board.GP14, 'A0': board.GP15,
}

pins = {}
for name, p in pin_map.items():
    pins[name] = digitalio.DigitalInOut(p)
    pins[name].direction = digitalio.Direction.OUTPUT

# 初期状態
pins['IC'].value = True
pins['CS'].value = True
pins['WE'].value = True
pins['A0'].value = False

data_pins = [pins[f'D{i}'] for i in range(8)]

def set_data(val):
    for i in range(8):
        data_pins[i].value = (val & (1 << i)) != 0

def write_ym2413(addr, data):
    pins['A0'].value = False
    set_data(addr)
    pins['CS'].value = False
    pins['WE'].value = False
    time.sleep(0.00001)
    pins['WE'].value = True
    pins['CS'].value = True
    time.sleep(0.00001)

    pins['A0'].value = True
    set_data(data)
    pins['CS'].value = False
    pins['WE'].value = False
    time.sleep(0.00001)
    pins['WE'].value = True
    pins['CS'].value = True
    time.sleep(0.00005)

def reset_ym2413():
    pins['IC'].value = False
    time.sleep(0.1)
    pins['IC'].value = True
    time.sleep(0.1)
    for i in range(0x40):
        write_ym2413(i, 0x00)

def init_rhythm():
    # リズム音用のボリューム (0x00が最大, 0x0Fが最小)
    write_ym2413(0x36, 0x00) # BD 
    write_ym2413(0x37, 0x00) # SD (bit7-4) / HH (bit3-0)
    write_ym2413(0x38, 0x00) # TC (bit7-4) / TOM (bit3-0)

    # リズム音の音程やノイズのための基本周波数設定
    write_ym2413(0x16, 0x20)
    write_ym2413(0x26, 0x28) 
    write_ym2413(0x17, 0x50) 
    write_ym2413(0x27, 0x2C) 
    write_ym2413(0x18, 0xC0) 
    write_ym2413(0x28, 0x26)

def set_instrument(channel, inst, volume):
    write_ym2413(0x30 + channel, (inst << 4) | (volume & 0x0F))

def note_to_ym2413(note):
    base_f = 49715.9
    freq = 440.0 * math.pow(2.0, (note - 69) / 12.0)
    fnum = int((freq * (1 << 19)) / base_f)
    block = 0
    while fnum > 511 and block < 7:
        fnum >>= 1
        block += 1
    if fnum > 511:
        fnum = 511
    return fnum, block

# GM楽器番号(0〜127)をYM2413のROM内蔵音色(1〜15)に簡易マッピング
# 音色リスト: 1:Violin, 2:Guitar, 3:Piano, 4:Flute, 5:Clarinet, 6:Oboe, 7:Trumpet, 
#            8:Organ, 9:Horn, 10:Synthesizer, 11:Harpsichord, 12:Vibraphone,
#            13:Synth Bass, 14:Acoustic Bass, 15:Electric Guitar
def gm_to_ym2413_inst(gm_program):
    mapping = {
        0: 3, 1: 3, 2: 3, 3: 3, 4: 11, 5: 11, 6: 11, 7: 11, # Pianos / E.Pianos
        8: 12, 9: 12, 10: 12, 11: 12, 12: 12, 13: 12, 14: 12, 15: 12, # Chromatic Percussion
        16: 8, 17: 8, 18: 8, 19: 8, 20: 8, 21: 8, 22: 8, 23: 8, # Organs
        24: 2, 25: 2, 26: 2, 27: 15, 28: 15, 29: 15, 30: 15, 31: 15, # Guitars
        32: 14, 33: 14, 34: 15, 35: 14, 36: 13, 37: 13, 38: 13, 39: 13, # Bass
        40: 1, 41: 1, 42: 1, 43: 1, 44: 1, 45: 1, # Strings / Orchestral
        56: 7, 57: 7, 58: 7, 59: 7, 60: 9, 61: 9, 62: 9, 63: 9, # Brass
        64: 5, 65: 5, 66: 5, 67: 6, 68: 6, 69: 6, 70: 6, 71: 5, # Reed
        72: 4, 73: 4, 74: 4, 75: 4, 76: 4, 77: 4, 78: 4, 79: 4, # Pipe
        80: 10, 81: 10, 82: 10, 88: 10, 89: 10, # Synth Lead / Pad
    }
    return mapping.get(gm_program, 3) # デフォルトはPiano(3)

# -----------------
# YM2413 割り当て管理
# -----------------
# リズムモード有効時はメロディチャンネルは0〜5の6和音になる
NUM_CHANNELS = 6
# どのMIDIチャンネルがどのYM2413チャンネルを使っているか・どのノートが鳴っているかを管理
ym2413_voices = {ch: {"note": None, "midi_ch": None} for ch in range(NUM_CHANNELS)}
midi_channel_inst = {ch: 3 for ch in range(16)} # デフォルトはPiano

# リズムモードの現在のレジスタ値（bit5=0x20 は常にON）
rhythm_state = 0x20

def allocate_channel(midi_ch):
    for ch in range(NUM_CHANNELS):
        if ym2413_voices[ch]["note"] is None:
            return ch
    # 空きがなければ最初のチャンネルを強制的に奪う（手抜き対応ですが実用上有効です）
    return 0

# -----------------
# カスタム MIDI Player
# -----------------
class YM2413_MIDIPlayer(adafruit_midi_parser.MIDIPlayer):
    def on_program_change(self, program, channel):
        # 楽器チェンジの記録
        print(f"Program Change => Ch:{channel} -> GM Instrument: {program}")
        midi_channel_inst[channel] = gm_to_ym2413_inst(program)

    def process_drum(self, note, velocity, is_on):
        global rhythm_state
        # Drum Map (GM) -> YM2413 Rhythm Bit
        # BD: 0x10, SD: 0x08, TOM: 0x04, TC: 0x02, HH: 0x01
        bit = 0x00
        if note in (35, 36):
            bit = 0x10 # Bass Drum
        elif note in (38, 40):
            bit = 0x08 # Snare Drum
        elif note in (41, 43, 45, 47, 48, 50):
            bit = 0x04 # Tom
        elif note in (49, 51, 52, 55, 57, 59):
            bit = 0x02 # Cymbal
        elif note in (42, 44, 46):
            bit = 0x01 # Hi-Hat

        if bit:
            if is_on and velocity > 0:
                rhythm_state |= bit
            else:
                rhythm_state &= ~bit
            write_ym2413(0x0E, rhythm_state)

    def on_note_on(self, note, velocity, channel):
        if channel == 9: # MIDIチャンネル10 (ドラム)
            self.process_drum(note, velocity, True)
            return

        if velocity == 0:
            self.on_note_off(note, velocity, channel)
            return

        ym_ch = allocate_channel(channel)
        ym2413_voices[ym_ch]["note"] = note
        ym2413_voices[ym_ch]["midi_ch"] = channel

        fnum, block = note_to_ym2413(note)
        inst = midi_channel_inst[channel]
        
        # 音色セット
        set_instrument(ym_ch, inst, max(0, 15 - (velocity >> 3))) # velocity (0-127) を YM volume (15-0) に変換
        
        # ピッチ・発音
        write_ym2413(0x10 + ym_ch, fnum & 0xFF)
        reg_20 = 0x10 | ((block & 0x07) << 1) | ((fnum >> 8) & 0x01)
        write_ym2413(0x20 + ym_ch, reg_20)

    def on_note_off(self, note, velocity, channel):
        if channel == 9: # MIDIチャンネル10 (ドラム)
            self.process_drum(note, velocity, False)
            return

        # このノートを鳴らしているYM2413チャンネルを探してオフにする
        for ch in range(NUM_CHANNELS):
            if ym2413_voices[ch]["note"] == note and ym2413_voices[ch]["midi_ch"] == channel:
                write_ym2413(0x20 + ch, 0x00) # Key Off
                ym2413_voices[ch]["note"] = None
                ym2413_voices[ch]["midi_ch"] = None

    def on_playback_complete(self):
        print("Playback complete!")
        reset_ym2413() # 全音オフ

# -----------------
# メイン実行部
# -----------------
reset_ym2413()
init_rhythm()

midi_file = "/song.mid"
print("\n--- YM2413 MIDI File Player ---")

if midi_file[1:] in os.listdir("/"):
    print(f"Loading {midi_file}...")
    parser = adafruit_midi_parser.MIDIParser()
    parser.parse(midi_file)
    print(f"Loaded! Tempo: {parser.bpm:.1f} BPM, Total tracks: {parser.num_tracks}, Event count: {len(parser.events)}")

    player = YM2413_MIDIPlayer(parser)
    print("Playing...")
    
    while not player.finished:
        player.play(loop=False) # 再生（メインループ内でイベントを処理）
else:
    print(f"File not found: {midi_file}")
