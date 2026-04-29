import time
import board
import digitalio
import usb_midi
import adafruit_midi
from adafruit_midi.note_on import NoteOn
from adafruit_midi.note_off import NoteOff

# ピンの設定
pin_map = {
    'D7': board.GP0,
    'D6': board.GP1,
    'D5': board.GP2,
    'D4': board.GP3,
    'D3': board.GP4,
    'D2': board.GP5,
    'D1': board.GP10,
    'D0': board.GP11,
    'IC': board.GP12,
    'CS': board.GP13,
    'WE': board.GP14,
    'A0': board.GP15,
}

# ピンの初期化
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
    # アドレス書き込み
    pins['A0'].value = False
    set_data(addr)
    pins['CS'].value = False
    pins['WE'].value = False
    time.sleep(0.00001) # 短いウェイト
    pins['WE'].value = True
    pins['CS'].value = True
    time.sleep(0.00001)

    # データ書き込み
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
    
    # 全レジスタの初期化 (0x00 - 0x38)
    for i in range(0x40):
        write_ym2413(i, 0x00)

def set_instrument(channel, inst, volume):
    # inst: 0-15 (0=Original, 1-15=ROM), volume: 0-15 (0=Max, 15=Min)
    write_ym2413(0x30 + channel, (inst << 4) | (volume & 0x0F))

def note_to_ym2413(note):
    # MIDIノート番号からF-NumberとBlock（オクターブ）を計算
    # マスタークロック 3.579545 MHz を想定
    import math
    freq = 440.0 * math.pow(2.0, (note - 69) / 12.0)
    
    # ブロック(オクターブ)の決定
    # freq = (MCLK / 72) * FNUM / 2^(19-BLOCK)
    # FNUM = freq * 2^(19-BLOCK) / 49715.9
    
    base_f = 49715.9
    block = 0
    fnum = 0
    
    for b in range(1, 8):
        f = freq * math.pow(2, 19 - b) / base_f
        if f >= 128 and f <= 343: # F-Numberは9ビット (基本的には128～511だが実用範囲)
            block = b - 1
            fnum = int(f)
            break
    if block == 0 and fnum == 0:
        fnum = int(freq * math.pow(2, 19) / base_f)
        if fnum > 511:
            fnum = 511

    return fnum, block

# 初期化プロセス
reset_ym2413()

# 全9チャンネルの初期化 (0x03=Piano)
for ch in range(9):
    set_instrument(ch, 0x03, 0x00)

print("Initialize MIDI...")
# MIDI入力のセットアップ
try:
    midi = adafruit_midi.MIDI(midi_in=usb_midi.ports[0], in_channel=0)
    print("YM2413 USB MIDI Synthesizer is ready (Polyphonic).")
except IndexError:
    print("Error: USB MIDI is not available check boot.py.")
    while True:
        time.sleep(1)

# 各チャンネルの現在鳴らしているノートを記録
active_notes = {ch: None for ch in range(9)}

def find_free_channel():
    for ch in range(9):
        if active_notes[ch] is None:
            return ch
    return None

while True:
    msg = midi.receive()
    if msg is not None:
        if isinstance(msg, NoteOn) and msg.velocity > 0:
            note = msg.note
            
            # 空きチャンネルを探す
            free_ch = find_free_channel()
            
            if free_ch is not None:
                fnum, block = note_to_ym2413(note)
                
                # F-Number 下位8ビット (0x10 + ch)
                write_ym2413(0x10 + free_ch, fnum & 0xFF)
                
                # Key ON (bit4), Block (bit1-3), F-Number 上位1ビット (bit0) (0x20 + ch)
                reg_20 = 0x10 | ((block & 0x07) << 1) | ((fnum >> 8) & 0x01)
                write_ym2413(0x20 + free_ch, reg_20)
                
                active_notes[free_ch] = note
            
        elif isinstance(msg, NoteOff) or (isinstance(msg, NoteOn) and msg.velocity == 0):
            note = msg.note
            
            # このノートを鳴らしているすべてのチャンネルをオフにする
            for ch in range(9):
                if active_notes[ch] == note:
                    # Key OFF: ピッチなどは維持してKeyフラグだけ落とす
                    # YM2413はレジスタの読み出しができないので、シンプルに0x00を書き込んでミュートします
                    write_ym2413(0x20 + ch, 0x00)
                    active_notes[ch] = None
