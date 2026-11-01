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
class GPSRec:
    def __init__(self):
        # - служебные -
        self.nSat = 0          # число спутников в эпохе
        self.prn  = 0          # PRN
        # - Строка 1: PRN / EPOCH / SV CLK
        self.af0 = 0.0         # Сдвиг часов спутника (секунда)
        self.af1 = 0.0         # Скорость ухода часов (сек./сек.)
        self.af2 = 0.0         # Ускорение ухода часов (сек./сек.^2)
        # - Строка 2: BROADCAST ORBIT - 1 -
        self.iode   = 0.0      # IODE
        self.crs    = 0.0      # Crs (метр)
        self.deltan = 0.0      # Delta n (радиан/секунда)
        self.m0     = 0.0      # M0 (радиан)
        # - Строка 3: BROADCAST ORBIT - 2 -
        self.cuc   = 0.0       # Cuc (радиан)
        self.e     = 0.0       # Эксцентриситет орбиты (e)
        self.cus   = 0.0       # Cus (радиан)
        self.sqrtA = 0.0       # sqrt(A) (метр^0.5)
        # - Строка 4: BROADCAST ORBIT - 3 -
        self.toe     = 0.0     # Время эфемерид (Toe) (секунда от начала GPS-недели)
        self.cic     = 0.0     # Cic (радиан)
        self.OMEGA  = 0.0      # OMEGA (радиан)
        self.cis     = 0.0     # CIS (радиан)
        # - Строка 5: BROADCAST ORBIT - 4 -
        self.i0       = 0.0    # наклон орбиты спутника относительно плоскости экватора (радиан)
        self.crc      = 0.0    # Crc (метр)
        self.omega    = 0.0    # omega (радиан)
        self.omegaDot = 0.0    # OMEGA DOT (радиан/секунда)
        # - Строка 6: BROADCAST ORBIT - 5 -
        self.iDot     = 0.0    # IDOT (радиан/секунда)
        self.codeL2   = 0.0    # Коды в диапазоне L2
        self.gpsWeekNo= 0      # Номер GPS-недели
        self.L2flag   = 0.0    # Флаг данных L2 P
        # - Строка 7: BROADCAST ORBIT - 6 -
        self.svaccur  = 0.0    # Точность положения спутника (метр)
        self.svhealth = 0.0    # Исправность
        self.tgd      = 0.0    # TGD (секунда)
        self.iodc     = 0.0    # IODC
        # - Строка 8: BROADCAST ORBIT - 7 -
        self.txTime = 0.0      # Время передачи сообщения (секунды GPS недели)
        self.fitInt = 0.0      # Интервал аппроксимации орбиты (часы)
        # - доп. поле из твоего кода -
        self.toc = 0.0         # время часов (сек от начала суток), используется в обработке
        self.freqNo = 0        # для совместимости (не используется для GPS)
        self.debugId = 0       # ID для отладки (копия PRN)
def rinex_get_nav_gps(file_nav):
    """
    читаем и формирует столбцы в порядке, как в файле.
      0: PRN               1: af0             2: af1            3: af2
      4: IODE              5: Crs             6: Delta n        7: M0
      8: Cuc               9: e               10: Cus           11: sqrtA
      12: Toe              13: Cic            14: OMEGA        15: Cis
      16: i0               17: Crc            18: omega         19: Omegadot
      20: IDOT             21: code_on_L2     22: GPS_week      23: L2flag
      24: sv_accuracy      25: sv_health      26: TGD           27: IODC
      28: transmission_time (t_Tx)      29: fit_interval (hours)
    """
    body = _read_body(file_nav)
    cols = []
    i = 0
    while i < len(body):
        if not body[i].strip():
            i += 1
            continue
        if i + 7 >= len(body):
            break

        lin1 = body[i]
        lin2 = body[i+1]
        lin3 = body[i+2]
        lin4 = body[i+3]
        lin5 = body[i+4]
        lin6 = body[i+5]
        lin7 = body[i+6]
        lin8 = body[i+7]
        i += 8

        #  Строка 1 

        prn_field = lin1[0:3].strip()
        if prn_field and prn_field[0].isalpha():     # RINEX3: "G01"
            if prn_field[0].upper() != 'G':
                continue                              # пропускаем не-GPS записи (если встретятся)
            prn = int(prn_field[1:])
        else:                                         # RINEX2: " 1"
            prn = int(prn_field)

        L1 = _to_floats(lin1[3:])[-3:]                # берём последние 3 числа = af0, af1, af2
        
        # prn = int(lin1[0:3])               
        # L1 = _to_floats(lin1[22:])         # преобразуем числа начиная с позиции 22 
        
        L2 = _to_floats(lin2)  
        L3 = _to_floats(lin3)  
        L4 = _to_floats(lin4)  
        L5 = _to_floats(lin5)  
        L6 = _to_floats(lin6)  
        L7 = _to_floats(lin7)  
        L8 = _to_floats(lin8)  
        col = [0.0]*30

        #  Строка 1 
        col[0] = float(prn)
        col[1] = L1[0] if len(L1) > 0 else 0.0  
        col[2] = L1[1] if len(L1) > 1 else 0.0  
        col[3] = L1[2] if len(L1) > 2 else 0.0  

        #  Строка 2 
        col[4]  = (L2[0] if len(L2)>0 else 0.0)  
        col[5]  = (L2[1] if len(L2)>1 else 0.0) 
        col[6]  = (L2[2] if len(L2)>2 else 0.0)  
        col[7]  = (L2[3] if len(L2)>3 else 0.0)  

        #  Строка 3 
        col[8]  = (L3[0] if len(L3)>0 else 0.0)  
        col[9]  = (L3[1] if len(L3)>1 else 0.0)  
        col[10] = (L3[2] if len(L3)>2 else 0.0)  
        col[11] = (L3[3] if len(L3)>3 else 0.0)  

        #  Строка 4 
        col[12] = (L4[0] if len(L4)>0 else 0.0)  
        col[13] = (L4[1] if len(L4)>1 else 0.0)  
        col[14] = (L4[2] if len(L4)>2 else 0.0)  
        col[15] = (L4[3] if len(L4)>3 else 0.0)  

        #  Строка 5 
        col[16] = (L5[0] if len(L5)>0 else 0.0)  
        col[17] = (L5[1] if len(L5)>1 else 0.0)  
        col[18] = (L5[2] if len(L5)>2 else 0.0)  
        col[19] = (L5[3] if len(L5)>3 else 0.0)  

        #  Строка 6 
        col[20] = (L6[0] if len(L6)>0 else 0.0)  
        col[21] = (L6[1] if len(L6)>1 else 0.0)  
        col[22] = (L6[2] if len(L6)>2 else 0.0)  
        col[23] = (L6[3] if len(L6)>3 else 0.0)  

        #  Строка 7 
        col[24] = (L7[0] if len(L7)>0 else 0.0)  
        col[25] = (L7[1] if len(L7)>1 else 0.0)  
        col[26] = (L7[2] if len(L7)>2 else 0.0)  
        col[27] = (L7[3] if len(L7)>3 else 0.0)  

        #  Строка 8 
        col[28] = (L8[0] if len(L8)>0 else 0.0)  
        col[29] = (L8[1] if len(L8)>1 else 0.0)

        cols.append(col)

    if not cols:
        return []
    n = len(cols)
    # теперь транспонируем 30×N
    eRdy = [[cols[j][i] for j in range(n)] for i in range(30)]
    return eRdy

def read_gps_ephemeris(file_nav):
    eRdy = rinex_get_nav_gps(file_nav)
    if not eRdy:
        return [], [], []

    # toe хранится в eRdy[12]
    toes = sorted({eRdy[12][c] for c in range(len(eRdy[0]))})
    # неделя GPS в eRdy[22]
    ephT = [[toe, int(eRdy[22][0]) if eRdy[22] else 0] for toe in toes]

    eph = [[None for _ in range(33)] for _ in range(len(toes))]
    ephSats = [[] for _ in range(len(toes))]

    for k, toe in enumerate(toes):
        cols = [n for n in range(len(eRdy[0])) if eRdy[12][n] == toe]
        nSat = len(cols)
        sats = []
        for n in cols:
            G = int(eRdy[0][n])   # PRN
            sats.append(G)
            r = GPSRec()
            r.nSat = nSat
            r.prn = G

            # - строка 1 -
            r.af0 = eRdy[1][n]
            r.af1 = eRdy[2][n]
            r.af2 = eRdy[3][n]

            # - строка 2 -
            r.iode   = eRdy[4][n]
            r.crs    = eRdy[5][n]
            r.deltan = eRdy[6][n]
            r.m0     = eRdy[7][n]

            # - строка 3 -
            r.cuc   = eRdy[8][n]
            r.e     = eRdy[9][n]
            r.cus   = eRdy[10][n]
            r.sqrtA = eRdy[11][n]

            # - строка 4 -
            r.toe     = eRdy[12][n]
            r.cic     = eRdy[13][n]
            r.OMEGA  = eRdy[14][n]
            r.cis     = eRdy[15][n]

            # - строка 5 -
            r.i0       = eRdy[16][n]
            r.crc      = eRdy[17][n]
            r.omega    = eRdy[18][n]
            r.omegaDot = eRdy[19][n]

            # - строка 6 -
            r.iDot      = eRdy[20][n]
            r.codeL2    = eRdy[21][n]
            r.gpsWeekNo = eRdy[22][n]
            r.L2flag    = eRdy[23][n]

            # - строка 7 -
            r.svaccur  = eRdy[24][n]
            r.svhealth = eRdy[25][n]
            r.tgd      = eRdy[26][n]
            r.iodc     = eRdy[27][n]

            # - строка 8 -
            r.txTime = eRdy[28][n]
            r.fitInt = eRdy[29][n]

            eph[k][G] = r
        ephSats[k] = sats
    return eph, ephSats, ephT

def load_nav_separate_GPS (GPS_FILE):
    """
    Загружает и парсит отдельные файлы эфемерид GPS и ГЛОНАСС.
    Возвращает кортеж из двух наборов:
    """
    gps, gpsSats, gpsT = read_gps_ephemeris(GPS_FILE)
    return (gps, gpsSats, gpsT)
