from nka_app.common import FLOAT_RE, Path

def _to_floats(s):
    s = s.replace('D', 'E').replace('d', 'E')
    return [float(m.group(0)) for m in FLOAT_RE.finditer(s)]

def _read_body(fp: str):
    lines = Path(fp).read_text(encoding="utf-8", errors="ignore").splitlines()
    # Ищем строку, содержащую 'END OF HEADER' — это конец заголовка RINEX-файла.
    for i, ln in enumerate(lines[:2000]):  # ограничиваем поиск первыми 2000 строками на случай повреждённого файла
        if 'END OF HEADER' in ln:
            # Возвращаем все строки, идущие после заголовка
            return lines[i+1:]
    # Если в файле нет строки 'END OF HEADER', возвращаем весь файл как есть.
    return lines

class GloRec:
    def __init__(self):
        # - служебное -
        self.nSat = 0        # количество спутников в эпохе
        self.prn  = 0        # PRN
        # - строка 1: RPRN / EPOCH / SV CLK -
        self.tauN   = 0.0    # Сдвиг часов спутника (cекунды) (-TauN)
        self.gammaN = 0.0    # Относительный сдвиг частоты (+GammaN)
        self.tb     = 0.0    # Время сообщения (tb)
        # - строка 2: BROADCAST ORBIT 1 -
        self.x   = 0.0       # X координата спутника (км)
        self.dx  = 0.0       # скорость по X (км/с)
        self.ddx = 0.0       # ускорение по X (км/с2)
        self.svhealth = 0.0  # Исправность (0=OK)      
        # - строка 3: BROADCAST ORBIT 2 -
        self.y   = 0.0       # Y координата спутника (км)
        self.dy  = 0.0       # скорость по Y (км/с)
        self.ddy = 0.0       # ускорение по Y (км/с2)
        self.freqNo = 0      # Номер частотного канала (-7 ... +13)
        # - строка 4: BROADCAST ORBIT 3 -
        self.z   = 0.0       # Z координата спутника (км)
        self.dz  = 0.0       # скорость по Z (км/с)
        self.ddz = 0.0       # ускорение по Z (км/с2)
        self.age = 0.0       # Возраст информации (дней)
        # - дополнительное -
        self.debugId = 0     # ID для отладки (копия PRN)

def rinex_get_nav_glonass(file_nav):
    """
    читаем и формирует столбцы в порядке, как в файле.
     0: PRN, 1: tauN, 2: gammaN, 3: tb,
     4: x,   5: dx,   6: ddx,    7: svhealth,
     8: y,   9: dy,  10: ddy,   11: freqNo,
     12: z,  13: dz,  14: ddz,   15:age 
    """

    # Считываем всё тело файла 
    body = _read_body(file_nav)
    cols = []  # сюда добавляем столбцы (по одному блоку спутника)
    i = 0
    while i < len(body):
        #  пропускаем пустые или нерелевантные строки 
        if not body[i].strip():
            i += 1
            continue

        if i + 3 >= len(body):  # блок не полный
            break

        #  читаем 4 строки блока спутника 
        l1 = body[i]
        l2 = body[i+1]
        l3 = body[i+2]
        l4 = body[i+3]
        i += 4

        #  конвертируем строки в массивы чисел 
        # RINEX 3: идентификатор R01, поля часов начинаются с позиции 23.
        is_v3 = l1[0:1].isalpha()
        prn = int(l1[1:3] if is_v3 else l1[0:3])
        L1 = _to_floats(l1[23:] if is_v3 else l1[22:])
        L2 = _to_floats(l2)        
        L3 = _to_floats(l3)        
        L4 = _to_floats(l4)        

        col = [0.0]*16

        # ===== Строка 1:  =====
        col[0] = float(prn)                    
        col[1] = L1[0] if len(L1)>0 else 0.0   
        col[2] = L1[1] if len(L1)>1 else 0.0   
        col[3] = L1[2] if len(L1)>2 else 0.0   

        # ===== Строка 2: координаты X =====
        col[4] = L2[0] if len(L2)>0 else 0.0   
        col[5] = L2[1] if len(L2)>1 else 0.0   
        col[6] = L2[2] if len(L2)>2 else 0.0   
        col[7] = L2[3] if len(L2)>3 else 0.0  

        # ===== Строка 3: координаты Y =====
        col[8]  = L3[0] if len(L3)>0 else 0.0  
        col[9]  = L3[1] if len(L3)>1 else 0.0  
        col[10] = L3[2] if len(L3)>2 else 0.0  
        col[11] = L3[3] if len(L3)>3 else 0.0  

        # ===== Строка 4: координаты Z =====
        col[12] = L4[0] if len(L4)>0 else 0.0  
        col[13] = L4[1] if len(L4)>1 else 0.0 
        col[14] = L4[2] if len(L4)>2 else 0.0  
        col[15] = L4[3] if len(L4)>3 else 0.0  
        
        # добавляем запись в общий список
        cols.append(col)

    if not cols:
        return []

    #  транспонируем (16×N) 
    n = len(cols)
    eRdyR = [[cols[j][i] for j in range(n)] for i in range(16)]
    return eRdyR

def read_glonass_ephemeris(file_nav):
    eRdyR = rinex_get_nav_glonass(file_nav)
    if not eRdyR:
        return [], [], []

    tbs = sorted({eRdyR[3][c] for c in range(len(eRdyR[0]))})

    ephR     = [[None for _ in range(33)] for _ in range(len(tbs))]  #
    ephRSats = [[] for _ in range(len(tbs))]
    ephRT    = [[tb, 0] for tb in tbs]  

    # Проходим по эпохам tb и собираем спутники этой эпохи
    for k, tb in enumerate(tbs):
        # Индексы столбцов, относящихся к текущей эпохе tb
        cols = [n for n in range(len(eRdyR[0])) if eRdyR[3][n] == tb]
        nSat = len(cols)
        sats = []

        for n in cols:
            R = int(eRdyR[0][n])  # PRN 
            sats.append(R)

            r = GloRec()
            r.nSat = nSat
            r.prn  = R

            #  строка 1: 
            r.tauN     = eRdyR[1][n]
            r.gammaN   = eRdyR[2][n]
            r.tb       = eRdyR[3][n]

            #  строка 2: 
            r.x        = eRdyR[4][n]
            r.dx       = eRdyR[5][n]
            r.ddx      = eRdyR[6][n]
            r.svhealth = eRdyR[7][n]

            #  строка 3:  
            r.y        = eRdyR[8][n]
            r.dy       = eRdyR[9][n]
            r.ddy      = eRdyR[10][n]
            r.freqNo   = eRdyR[11][n]

            #  строка 4: 
            r.z        = eRdyR[12][n]
            r.dz       = eRdyR[13][n]
            r.ddz      = eRdyR[14][n]
            r.age      = eRdyR[15][n]


            r.debugId = R
            ephR[k][R] = r

        ephRSats[k] = sats

    return ephR, ephRSats, ephRT

def load_nav_separate_GLO (GLO_FILE):
    """
    Загружает и парсит отдельные файлы эфемерид GPS и ГЛОНАСС.
    Возвращает кортеж из двух наборов:
    """
    glo, gloSats, gloT = read_glonass_ephemeris(GLO_FILE)
    return  (glo, gloSats, gloT)
