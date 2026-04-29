import time
import board
import digitalio

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

def init_rhythm():
    # リズム音用のボリューム (0x00が最大, 0x0Fが最小)
    write_ym2413(0x36, 0x00) # BD 
    write_ym2413(0x37, 0x00) # SD (bit7-4) / HH (bit3-0)
    write_ym2413(0x38, 0x00) # TC (bit7-4) / TOM (bit3-0)

    # リズム音の音程やノイズのための基本周波数設定 (これを設定しないと本来のドラム音が鳴りません)
    # Ch7(0x16, 0x26): BD
    # Ch8(0x17, 0x27): SD/HH
    # Ch9(0x18, 0x28): TOM/TC
    write_ym2413(0x16, 0x20)
    write_ym2413(0x26, 0x28) 
    
    write_ym2413(0x17, 0x50) 
    write_ym2413(0x27, 0x2C) 
    
    write_ym2413(0x18, 0xC0) 
    write_ym2413(0x28, 0x26)

def play_drum(bd=False, sd=False, tom=False, tc=False, hh=False):
    # レジスタ 0x0E (Rhythm Control)
    # bit 5: Rhythm Enable
    # bit 4: Bass Drum (BD)
    # bit 3: Snare Drum (SD)
    # bit 2: Tom-tom (TOM)
    # bit 1: Top Cymbal (TC)
    # bit 0: Hi-Hat (HH)
    
    val = 0x20 # Rhythm Enable
    if bd: val |= 0x10
    if sd: val |= 0x08
    if tom: val |= 0x04
    if tc: val |= 0x02
    if hh: val |= 0x01
    
    write_ym2413(0x0E, val)


print("Initializing YM2413 Rhythm Mode...")
reset_ym2413()
init_rhythm()

# 順番に鳴らすドラムリスト
drums = [
    ("Bass Drum",  True, False, False, False, False),
    ("Snare Drum", False, True, False, False, False),
    ("Tom-Tom",    False, False, True, False, False),
    ("Top Cymbal", False, False, False, True, False),
    ("Hi-Hat",     False, False, False, False, True),
]

while True:
    for name, bd, sd, tom, tc, hh in drums:
        print(f"Playing... {name}")
        play_drum(bd, sd, tom, tc, hh)
        time.sleep(0.1) # 0.1秒鳴らす
        
        # 音を止める
        play_drum()
        time.sleep(0.4) # 0.4秒間隔をあける
        
    print("Loop reset\n")
    time.sleep(1) # 一周したら1秒待機
