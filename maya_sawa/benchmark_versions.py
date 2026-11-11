"""Versioned Taiwan semiconductor benchmark line-ups.

A version is a whole line-up with the reason it was chosen. Changing the line-up means appending a
version here; the newest one is applied to the `benchmark` table once, and earlier ones stay on record.
Company tuples are (code, name, segment, role, significance).
"""

LEADER, PEER = "龍頭", "對照"

_V1 = {
    "2454": ("聯發科", "IC 設計與終端應用", "以手機 SoC 觀察設計公司如何在效能、功耗與整合度之間取捨。對照產品組合與研發揭露，理解晶片如何轉化成終端裝置功能。"),
    "2303": ("聯電", "晶圓製造與廠務", "用成熟及特殊製程觀察代工如何把設計變成可量產的晶片。對照不同廠房與製程組合，有助於區分製造能力與產能利用率。"),
    "6488": ("環球晶", "8 吋與 12 吋矽晶圓", "以同一家材料商比較晶圓尺寸、產品規格與擴產配置。追蹤資本支出和產能時，將上游裸晶圓供給與晶圓代工產能分開。"),
    "2330": ("台積電", "專業晶圓代工與 CoWoS", "同時觀察邏輯晶圓製造和異質整合封裝，理解 AI 晶片效能如何受到運算晶粒、記憶體頻寬和封裝能力共同影響。"),
    "6937": ("天虹", "PVD、PECVD、ALD 薄膜設備", "比較不同沉積方法的膜厚控制、覆蓋性和設備用途，並用產品線與研發揭露觀察設備商如何把製程需求變成可銷售機台。"),
    "3583": ("辛耘", "晶圓濕蝕刻", "觀察濕製程設備如何透過藥液、流量與時間控制材料移除，並比較設備銷售和晶圓再生服務這兩種業務。"),
    "3131": ("弘塑", "晶圓清洗與濕製程設備", "從台灣自製設備商的角度，觀察設備如何滿足晶圓清洗、蝕刻均勻度與量產要求，以及前段和封裝應用的差異。"),
    "1785": ("光洋科", "濺鍍靶材", "以靶材連結原料純度、濺鍍薄膜與金屬回收。閱讀年報時可分辨材料研製與循環回收兩種價值來源。"),
    "4772": ("台特化", "半導體特殊氣體", "透過矽烷類與其他特氣觀察純度、製造及供應穩定性如何影響晶圓製程，並追蹤產品開發與產能的公開揭露。"),
    "3413": ("京鼎", "設備真空腔體與精密零件", "以腔體和真空零件觀察設備供應鏈的加工精度、潔淨度與可靠性要求，理解零件製造和整機整合的分工。"),
    "5536": ("聖暉*", "無塵室與廠務工程", "觀察空氣、微粒與公用設施如何影響晶圓廠量產環境。工程業務也提供辨識建廠投資與晶片產出的時間差的案例。"),
    "3455": ("由田", "晶圓光學檢測與良率", "利用自動光學檢測產品觀察缺陷如何被發現、分類與回饋至製程。比較檢測速度、解析度和誤判率的工程取捨。"),
    "4949": ("有成精密", "離子植入設備零件與維護", "從離子植入機的特殊材料零件及維護切入，理解摻雜設備的耗損與穩定度如何影響量產，並分辨設備服務與晶片製造。"),
    "1560": ("中砂", "CMP 鑽石碟", "用拋光墊修整耗材理解平坦度與良率如何連到耗材需求。年度報告可用來追蹤產品組合與製程應用的變化。"),
    "3711": ("日月光投控", "封裝、測試與異質整合", "對照封裝結構、測試及異質整合服務，理解晶粒出廠後如何形成可裝配、可驗證的產品，以及不同封裝方案的適用情境。"),
    "3587": ("閎康", "材料分析與可靠度驗證", "從材料分析、可靠度與失效分析理解更換材料前需要建立哪些證據，以及如何把檢測結果用於失效定位與供應商驗證。"),
}


def _v1(*codes):
    return [(code, _V1[code][0], _V1[code][1], PEER, _V1[code][2]) for code in codes]


def _kept(code, role, segment=None):
    name, old_segment, significance = _V1[code]
    return (code, name, segment or old_segment, role, significance)


VERSIONS = (
    {
        "version": 1,
        "name": "台積電本土設備鏈觀察名單",
        "rationale": "第一版以製程步驟選公司，16 家裡設備、耗材與廠務占 9 家，IC 設計與封測各只有 1 家，"
                     "沒有記憶體、矽智財、測試介面與載板。適合觀察晶圓廠資本支出，不足以代表整個產業。",
        "layers": [
            {"title": "材料與矽晶圓", "stages": [{"title": "材料與矽晶圓", "companies": _v1("1785", "4772", "6488")}]},
            {"title": "晶圓製造與廠務", "stages": [{"title": "晶圓製造與廠務", "companies": _v1("2303", "2330", "5536")}]},
            {"title": "製程設備、檢測與耗材", "stages": [{"title": "製程設備、檢測與耗材", "companies": _v1("1560", "3131", "3413", "3455", "3583", "3587", "4949", "6937")}]},
            {"title": "IC 設計", "stages": [{"title": "IC 設計", "companies": _v1("2454")}]},
            {"title": "封裝與測試", "stages": [{"title": "封裝與測試", "companies": _v1("3711")}]},
        ],
        "flows": [],
    },
    {
        "version": 2,
        "name": "台灣半導體全產業骨幹",
        "rationale": "第二版改以產業分工選公司：每個環節一家龍頭加一家對照公司，共 11 個環節 22 家。"
                     "補上記憶體、矽智財與 ASIC、測試介面、載板與專業測試，設備與耗材由 9 家減為 4 家。"
                     "圖的流向改為設計公司委託晶圓廠製造、材料設備與廠務供應晶圓廠、晶圓廠出貨到後段。",
        "layers": [
            {"key": "design", "title": "設計：決定要做什麼晶片", "stages": [
                {"title": "IC 設計", "companies": [
                    _kept("2454", LEADER),
                    ("2379", "瑞昱", "網通與多媒體 IC 設計", PEER, "以網通、音訊與電腦周邊晶片對照聯發科的手機平台，觀察成熟製程產品如何靠整合度與出貨量獲利，以及終端需求變化如何反映在庫存。"),
                ]},
                {"title": "矽智財與 ASIC 設計服務", "companies": [
                    ("3443", "創意", "ASIC 設計服務與矽智財", LEADER, "觀察雲端業者自研晶片如何委託設計服務公司完成後段設計並導入先進製程與先進封裝，區分委託設計收入與量產收入。"),
                    ("3661", "世芯-KY", "高效能運算 ASIC 設計服務", PEER, "以高效能運算客製晶片對照創意，觀察客戶集中度、先進製程案量與量產時程如何左右營收，理解 ASIC 專案的階段性。"),
                ]},
            ]},
            {"key": "inputs", "title": "材料與設備：晶圓廠買什麼", "stages": [
                {"title": "矽晶圓與特用材料", "companies": [
                    _kept("6488", LEADER),
                    _kept("4772", PEER),
                ]},
                {"title": "製程設備與零組件", "companies": [
                    _kept("3131", LEADER, "先進封裝濕製程設備"),
                    _kept("3413", PEER),
                ]},
            ]},
            {"key": "support", "title": "廠務與驗證：晶圓廠靠什麼量產", "stages": [
                {"title": "無塵室與廠務工程", "companies": [
                    ("2404", "漢唐", "無塵室與機電系統整合", LEADER, "以晶圓廠無塵室與機電統包工程觀察建廠進度，在手工程與認列時點可用來對照晶圓廠資本支出到實際產出的時間差。"),
                    _kept("5536", PEER),
                ]},
                {"title": "材料分析與可靠度驗證", "companies": [
                    _kept("3587", LEADER),
                    ("3289", "宜特", "驗證分析與可靠度測試", PEER, "以可靠度驗證、故障分析與車用驗證對照閎康，觀察新製程與新材料導入時驗證需求如何先於量產出現。"),
                ]},
            ]},
            {"key": "fab", "title": "晶圓製造：把設計做成晶片", "stages": [
                {"title": "晶圓代工", "companies": [
                    _kept("2330", LEADER),
                    _kept("2303", PEER, "成熟與特殊製程晶圓代工"),
                ]},
                {"title": "記憶體", "companies": [
                    ("2408", "南亞科", "DRAM 製造", LEADER, "以 DRAM 觀察記憶體的價格循環、製程世代轉換與資本支出節奏，對照邏輯代工理解標準型產品與客製產品的獲利差異。"),
                    ("2344", "華邦電", "利基型 DRAM 與編碼型快閃記憶體", PEER, "以利基型記憶體對照南亞科，觀察車用與工控等長週期應用如何使價格波動小於標準型 DRAM，以及產能如何在產品間調配。"),
                ]},
            ]},
            {"key": "backend", "title": "後段：把晶片變成可出貨的產品", "stages": [
                {"title": "封裝與測試", "companies": [
                    _kept("3711", LEADER),
                    ("2449", "京元電子", "晶圓與成品專業測試", PEER, "以專業測試對照日月光的封裝業務，觀察 AI 晶片測試時間拉長如何帶動測試產能與資本支出，分辨封裝與測試的需求來源。"),
                ]},
                {"title": "測試介面", "companies": [
                    ("6515", "穎崴", "測試座與探針卡", LEADER, "以高階測試座觀察晶片腳數、功耗與頻率提高時測試介面如何跟著升級，介面需求通常早於晶片放量出現。"),
                    ("6223", "旺矽", "探針卡與測試設備", PEER, "以探針卡對照穎崴的測試座，分辨晶圓階段與成品階段的測試耗材，並觀察客製晶片案量如何反映在探針卡出貨。"),
                ]},
                {"title": "IC 載板", "companies": [
                    ("3037", "欣興", "ABF 與 BT 載板", LEADER, "以載板觀察晶片面積與層數增加如何消耗產能，載板的供需與擴產是高效能運算晶片能否如期出貨的條件之一。"),
                    ("8046", "南電", "ABF 載板", PEER, "以 ABF 載板比重較高的南電對照欣興，觀察載板報價、稼動率與產品組合在景氣循環中的變化。"),
                ]},
            ]},
        ],
        "flows": [
            {"from": "design", "to": "fab", "label": "委託製造"},
            {"from": "inputs", "to": "fab", "label": "供應材料與機台"},
            {"from": "support", "to": "fab", "label": "建廠與驗證"},
            {"from": "fab", "to": "backend", "label": "晶圓出貨"},
        ],
    },
    {
        "version": 3,
        "name": "各環節只留龍頭",
        "rationale": "第三版每個環節只留龍頭一家，共 12 家。Benchmark 是用股東會年報定調產業指引與景氣位置的量尺，"
                     "不是買進標的，不需要同環節再放一家對照。晶圓代工分成先進與成熟製程兩個環節，因為兩者的景氣循環不同步。",
        "layers": [
            {"key": "design", "title": "設計：決定要做什麼晶片", "stages": [
                {"title": "自有產品 IC 設計", "companies": [("2454", "聯發科", "IC 設計與終端應用", LEADER, "看手機與消費性電子的終端需求、庫存水位，以及經營階層對下一年出貨與產品組合的展望。")]},
                {"title": "代客設計（ASIC）", "companies": [("3443", "創意", "ASIC 設計服務與矽智財", LEADER, "看雲端業者自研晶片的委託設計案量與量產時程，這是 AI 客製晶片需求最早出現的地方。")]},
            ]},
            {"key": "inputs", "title": "材料與設備：晶圓廠買什麼", "stages": [
                {"title": "矽晶圓", "companies": [("6488", "環球晶", "8 吋與 12 吋矽晶圓", LEADER, "看長約價格、客戶庫存去化與擴產進度，矽晶圓出貨反映整體晶圓投片量的方向。")]},
                {"title": "製程設備", "companies": [("3131", "弘塑", "先進封裝濕製程設備", LEADER, "看在手訂單與交機時程，設備訂單反映晶圓廠與封裝廠對未來一到兩年產能的判斷。")]},
            ]},
            {"key": "support", "title": "廠務與驗證：晶圓廠靠什麼量產", "stages": [
                {"title": "無塵室與廠務工程", "companies": [("2404", "漢唐", "無塵室與機電系統整合", LEADER, "看在手工程金額與認列進度，建廠工程是晶圓廠資本支出落地的第一站。")]},
                {"title": "材料分析與可靠度驗證", "companies": [("3587", "閎康", "材料分析與可靠度驗證", LEADER, "看分析與驗證委案量，新製程與新材料的研發活動會先反映在這裡，早於量產。")]},
            ]},
            {"key": "fab", "title": "晶圓製造：把設計做成晶片", "stages": [
                {"title": "先進製程晶圓代工", "companies": [("2330", "台積電", "專業晶圓代工與 CoWoS", LEADER, "看資本支出規劃、各應用平台的成長展望與先進封裝產能，這是全產業指引的定錨。")]},
                {"title": "成熟製程晶圓代工", "companies": [("2303", "聯電", "成熟與特殊製程晶圓代工", LEADER, "看稼動率、平均售價與車用工控需求，成熟製程的景氣循環和先進製程不同步。")]},
                {"title": "記憶體", "companies": [("2408", "南亞科", "DRAM 製造", LEADER, "看 DRAM 報價、位元出貨成長與資本支出，記憶體是半導體裡循環最明顯的產品。")]},
            ]},
            {"key": "backend", "title": "後段：把晶片變成可出貨的產品", "stages": [
                {"title": "封裝與測試", "companies": [("3711", "日月光投控", "封裝、測試與異質整合", LEADER, "看封測稼動率、先進封裝營收比重與資本支出，反映晶片實際出貨的量。")]},
                {"title": "測試介面", "companies": [("6515", "穎崴", "測試座與探針卡", LEADER, "看高階測試座的接單與新產品導入，測試介面需求通常早於晶片放量出現。")]},
                {"title": "IC 載板", "companies": [("3037", "欣興", "ABF 與 BT 載板", LEADER, "看載板報價、稼動率與擴產節奏，載板供需是高效能運算晶片能否如期出貨的條件。")]},
            ]},
        ],
        "flows": [
            {"from": "design", "to": "fab", "label": "委託製造"},
            {"from": "inputs", "to": "fab", "label": "供應材料與機台"},
            {"from": "support", "to": "fab", "label": "建廠與驗證"},
            {"from": "fab", "to": "backend", "label": "晶圓出貨"},
        ],
        # Company-to-company relations, so the picture says why each one matters. Two companies with no
        # arrow between them (聯發科 sells its own chips, 創意 designs chips for others) are separate stages.
        "terminals": [{"key": "market", "title": "終端產品：手機、伺服器、車用"}],
        "links": [
            {"from": "2454", "to": "2330", "label": "先進製程投片"},
            {"from": "2454", "to": "2303", "label": "成熟製程投片"},
            {"from": "3443", "to": "2330", "label": "替雲端客戶設計後投片"},
            {"from": "6488", "to": "2330", "label": "矽晶圓"},
            {"from": "6488", "to": "2303", "label": "矽晶圓"},
            {"from": "6488", "to": "2408", "label": "矽晶圓"},
            {"from": "3131", "to": "2330", "label": "先進封裝濕製程機台"},
            {"from": "3131", "to": "3711", "label": "濕製程機台"},
            {"from": "2404", "to": "2330", "label": "無塵室與機電工程"},
            {"from": "3587", "to": "2330", "label": "材料與故障分析"},
            {"from": "3587", "to": "2454", "label": "晶片除錯與驗證"},
            {"from": "2330", "to": "3711", "label": "晶圓送封裝測試"},
            {"from": "2303", "to": "3711", "label": "晶圓送封裝測試"},
            {"from": "6515", "to": "3711", "label": "測試座"},
            {"from": "3037", "to": "3711", "label": "IC 載板"},
            {"from": "3711", "to": "market", "label": "成品晶片"},
            {"from": "2408", "to": "market", "label": "記憶體"},
        ],
    },
    {
        "version": 4,
        "name": "加入需求端與海外龍頭",
        "rationale": "第四版在台灣供應鏈兩端補上海外龍頭，共 19 家。最右邊加上需求端：Alphabet、Meta、Microsoft、Amazon "
                     "四家雲端服務商各自讀股東年報的資本支出與 AI 基礎建設說法，因為四家的展望不同，不合併成一個節點。"
                     "設計端加 NVIDIA，它是台積電先進製程與 CoWoS 的最大客戶。記憶體加 SK 海力士（HBM 龍頭，"
                     "NVIDIA 的主要 HBM 供應商），與看標準型 DRAM 的南亞科分成兩個環節，因為兩者的循環不同步。"
                     "後段加愛德萬測試機台，AI 晶片與 HBM 的測試時間拉長是後段景氣的主要訊號。"
                     "每家都必須能從官方來源取得最新一份股東年報才列入：美國走 SEC 的股東年報（ARS），"
                     "愛德萬走公司官網的統合報告書，SK 海力士走 OpenDART 的事業報告書。",
        "layers": [
            {"key": "design", "title": "設計：決定要做什麼晶片", "stages": [
                {"title": "AI 加速器", "companies": [("NVDA-US", "NVIDIA", "GPU 與 AI 加速器", LEADER, "看資料中心營收展望、供給限制與新架構時程，這是 AI 晶片需求最直接的訊號，也是台積電先進製程與 CoWoS 產能的最大買家。")]},
                {"title": "自有產品 IC 設計", "companies": [("2454", "聯發科", "IC 設計與終端應用", LEADER, "看手機與消費性電子的終端需求、庫存水位，以及經營階層對下一年出貨與產品組合的展望。")]},
                {"title": "代客設計（ASIC）", "companies": [("3443", "創意", "ASIC 設計服務與矽智財", LEADER, "看雲端業者自研晶片的委託設計案量與量產時程，這是 AI 客製晶片需求最早出現的地方。")]},
            ]},
            {"key": "inputs", "title": "材料與設備：晶圓廠買什麼", "stages": [
                {"title": "矽晶圓", "companies": [("6488", "環球晶", "8 吋與 12 吋矽晶圓", LEADER, "看長約價格、客戶庫存去化與擴產進度，矽晶圓出貨反映整體晶圓投片量的方向。")]},
                {"title": "製程設備", "companies": [("3131", "弘塑", "先進封裝濕製程設備", LEADER, "看在手訂單與交機時程，設備訂單反映晶圓廠與封裝廠對未來一到兩年產能的判斷。")]},
            ]},
            {"key": "support", "title": "廠務與驗證：晶圓廠靠什麼量產", "stages": [
                {"title": "無塵室與廠務工程", "companies": [("2404", "漢唐", "無塵室與機電系統整合", LEADER, "看在手工程金額與認列進度，建廠工程是晶圓廠資本支出落地的第一站。")]},
                {"title": "材料分析與可靠度驗證", "companies": [("3587", "閎康", "材料分析與可靠度驗證", LEADER, "看分析與驗證委案量，新製程與新材料的研發活動會先反映在這裡，早於量產。")]},
            ]},
            {"key": "fab", "title": "晶圓製造：把設計做成晶片", "stages": [
                {"title": "先進製程晶圓代工", "companies": [("2330", "台積電", "專業晶圓代工與 CoWoS", LEADER, "看資本支出規劃、各應用平台的成長展望與先進封裝產能，這是全產業指引的定錨。")]},
                {"title": "成熟製程晶圓代工", "companies": [("2303", "聯電", "成熟與特殊製程晶圓代工", LEADER, "看稼動率、平均售價與車用工控需求，成熟製程的景氣循環和先進製程不同步。")]},
                {"title": "AI 記憶體（HBM）", "companies": [("000660-KR", "SK 海力士", "HBM 與 DRAM", LEADER, "看 HBM 產能、世代轉換與客戶長約，AI 記憶體的供給決定加速器能出多少貨，循環也和標準型 DRAM 不同步。")]},
                {"title": "標準型與利基型 DRAM", "companies": [("2408", "南亞科", "DRAM 製造", LEADER, "看 DRAM 報價、位元出貨成長與資本支出，記憶體是半導體裡循環最明顯的產品。")]},
            ]},
            {"key": "backend", "title": "後段：把晶片變成可出貨的產品", "stages": [
                {"title": "封裝與測試", "companies": [("3711", "日月光投控", "封裝、測試與異質整合", LEADER, "看封測稼動率、先進封裝營收比重與資本支出，反映晶片實際出貨的量。")]},
                {"title": "測試機台", "companies": [("6857-JP", "愛德萬", "SoC 與記憶體測試機台", LEADER, "看 SoC 與 HBM 測試機的訂單與交期，AI 晶片測試時間拉長，測試機需求通常早於晶片放量出現。")]},
                {"title": "測試介面", "companies": [("6515", "穎崴", "測試座與探針卡", LEADER, "看高階測試座的接單與新產品導入，測試介面需求通常早於晶片放量出現。")]},
                {"title": "IC 載板", "companies": [("3037", "欣興", "ABF 與 BT 載板", LEADER, "看載板報價、稼動率與擴產節奏，載板供需是高效能運算晶片能否如期出貨的條件。")]},
            ]},
            {"key": "demand", "title": "需求端：雲端資本支出", "stages": [
                {"title": "雲端服務商", "companies": [
                    ("GOOGL-US", "Alphabet", "Google Cloud 與自研 TPU", LEADER, "看資本支出指引與 Google Cloud 的產能限制說法，同時採購 GPU 與自研 TPU，可以看出通用 GPU 與客製晶片的比重變化。"),
                    ("MSFT-US", "Microsoft", "Azure 與 AI 基礎建設", LEADER, "看資本支出與 Azure 產能是否仍供不應求，經營階層對 AI 需求與資料中心建置節奏的說法是需求端最常被引用的指引。"),
                    ("AMZN-US", "Amazon", "AWS 與自研 Trainium", LEADER, "看 AWS 資本支出與自研 Trainium 的規模，雲端市占最大的業者投資節奏決定整體資料中心需求的底部。"),
                    ("META-US", "Meta", "AI 訓練與推論叢集", LEADER, "看資本支出指引與 AI 叢集規模，Meta 不出租算力，投資完全用在自家 AI，反映的是模型訓練本身的需求。"),
                ]},
            ]},
        ],
        "flows": [
            {"from": "design", "to": "fab", "label": "委託製造"},
            {"from": "inputs", "to": "fab", "label": "供應材料與機台"},
            {"from": "support", "to": "fab", "label": "建廠與驗證"},
            {"from": "fab", "to": "backend", "label": "晶圓出貨"},
            {"from": "backend", "to": "demand", "label": "AI 伺服器晶片"},
        ],
        "terminals": [{"key": "market", "title": "終端產品：手機、PC、車用"}],
        "links": [
            {"from": "NVDA-US", "to": "2330", "label": "先進製程與 CoWoS 投片"},
            {"from": "2454", "to": "2330", "label": "先進製程投片"},
            {"from": "2454", "to": "2303", "label": "成熟製程投片"},
            {"from": "3443", "to": "2330", "label": "替雲端客戶設計後投片"},
            {"from": "6488", "to": "2330", "label": "矽晶圓"},
            {"from": "6488", "to": "2303", "label": "矽晶圓"},
            {"from": "6488", "to": "2408", "label": "矽晶圓"},
            {"from": "3131", "to": "2330", "label": "先進封裝濕製程機台"},
            {"from": "3131", "to": "3711", "label": "濕製程機台"},
            {"from": "2404", "to": "2330", "label": "無塵室與機電工程"},
            {"from": "3587", "to": "2330", "label": "材料與故障分析"},
            {"from": "3587", "to": "2454", "label": "晶片除錯與驗證"},
            {"from": "000660-KR", "to": "2330", "label": "HBM 送 CoWoS 封裝"},
            {"from": "6857-JP", "to": "3711", "label": "SoC 測試機台"},
            {"from": "6857-JP", "to": "000660-KR", "label": "HBM 測試機台"},
            {"from": "2330", "to": "3711", "label": "晶圓送封裝測試"},
            {"from": "2303", "to": "3711", "label": "晶圓送封裝測試"},
            {"from": "6515", "to": "3711", "label": "測試座"},
            {"from": "3037", "to": "3711", "label": "IC 載板"},
            {"from": "NVDA-US", "to": "GOOGL-US", "label": "AI 加速器"},
            {"from": "NVDA-US", "to": "MSFT-US", "label": "AI 加速器"},
            {"from": "NVDA-US", "to": "AMZN-US", "label": "AI 加速器"},
            {"from": "NVDA-US", "to": "META-US", "label": "AI 加速器"},
            {"from": "3711", "to": "market", "label": "成品晶片"},
            {"from": "2408", "to": "market", "label": "記憶體"},
        ],
    },
)


# Version 5 keeps version 4 and adds the rack components around the chips. Built from version 4 so the shared
# stages cannot drift apart between the two records.
_V4 = VERSIONS[3]
VERSIONS = VERSIONS + ({
    "version": 5,
    "name": "加入機櫃元件",
    "rationale": "第五版在第四版之外加上晶片以外、AI 機櫃一定要用的四個環節，共 23 家，並統一圖的讀法：每條箭頭都從供應者指向客戶，線型代表交付的是材料設備、代工製造、服務還是產品。"
                 "台光電看高速銅箔基板，"
                 "伺服器與交換器的板材升級不受銅轉光影響（被光取代的是銅線互連，不是電路板）；台達電看資料中心電源與散熱，"
                 "機櫃功率密度上升讓需求方向明確；Lumentum 看光通訊雷射，是銅轉光中受惠的一端；村田看 MLCC，"
                 "需求大部分來自消費電子與車用，放進來是當整體電子業庫存循環的溫度計，不是 AI 需求的訊號。"
                 "銅線互連、玻璃基板與 ABF 膜材不列入：前者方向有爭議，玻璃基板量產時程未定，ABF 膜材龍頭的年報以食品為主。",
    "layers": [*_V4["layers"][:-1], {"key": "rack", "title": "機櫃元件：晶片以外的板材、電源與互連", "stages": [
        {"title": "銅箔基板（CCL）", "companies": [("2383", "台光電", "高速與低損耗銅箔基板", LEADER, "看 AI 伺服器與交換器的高階板材出貨與擴產，板層數與材料等級升級是中長期確定的方向，不受銅轉光影響。")]},
        {"title": "資料中心電源與散熱", "companies": [("2308", "台達電", "伺服器電源、散熱與資料中心基礎設施", LEADER, "看資料中心電源與液冷的營收比重與擴產，機櫃功率密度上升讓每座資料中心的電源與散熱用量持續增加。")]},
        {"title": "光互聯", "companies": [("LITE-US", "Lumentum", "光通訊雷射（EML、CPO 光源）", LEADER, "看資料中心雷射的產能與交期，傳輸速率升級與銅轉光都會增加雷射用量，是光互聯需求最上游的訊號。")]},
        {"title": "被動元件", "companies": [("6981-JP", "村田製作所", "MLCC 與電子元件", LEADER, "看 MLCC 稼動率、庫存與各應用需求，被動元件反映整體電子業的庫存循環；AI 伺服器用量增加，但需求主體仍是消費電子與車用。")]},
    ]}, _V4["layers"][-1]],
    "flows": [*_V4["flows"], {"from": "rack", "to": "demand", "label": "AI 機櫃元件"}],
    "terminals": [*_V4["terminals"], {"key": "rack", "title": "AI 資料中心機櫃"}],
    # Every arrow runs supplier -> customer; `kind` says what is handed over (legend on the page). A link may end
    # at a layer key ("demand") when the relation is with the whole group rather than one named company.
    "links": [
        {"from": "6488", "to": "2330", "kind": "supply", "label": "矽晶圓"},
        {"from": "6488", "to": "2303", "kind": "supply", "label": "矽晶圓"},
        {"from": "6488", "to": "2408", "kind": "supply", "label": "矽晶圓"},
        {"from": "3131", "to": "2330", "kind": "supply", "label": "先進封裝濕製程機台"},
        {"from": "3131", "to": "3711", "kind": "supply", "label": "濕製程機台"},
        {"from": "6857-JP", "to": "3711", "kind": "supply", "label": "SoC 測試機台"},
        {"from": "6857-JP", "to": "000660-KR", "kind": "supply", "label": "HBM 測試機台"},
        {"from": "6515", "to": "3711", "kind": "supply", "label": "測試座"},
        {"from": "3037", "to": "3711", "kind": "supply", "label": "IC 載板"},
        {"from": "000660-KR", "to": "NVDA-US", "kind": "supply", "label": "HBM"},
        {"from": "2383", "to": "rack", "kind": "supply", "label": "高速 CCL 板材"},
        {"from": "2308", "to": "rack", "kind": "supply", "label": "電源與散熱"},
        {"from": "LITE-US", "to": "rack", "kind": "supply", "label": "光收發模組雷射"},
        {"from": "6981-JP", "to": "rack", "kind": "supply", "label": "MLCC"},
        {"from": "2330", "to": "NVDA-US", "kind": "manufacture", "label": "先進製程與 CoWoS"},
        {"from": "2330", "to": "2454", "kind": "manufacture", "label": "先進製程"},
        {"from": "2303", "to": "2454", "kind": "manufacture", "label": "成熟製程"},
        {"from": "2330", "to": "3443", "kind": "manufacture", "label": "ASIC 晶圓"},
        {"from": "3711", "to": "2454", "kind": "manufacture", "label": "封裝測試"},
        {"from": "3711", "to": "NVDA-US", "kind": "manufacture", "label": "封裝測試"},
        {"from": "2404", "to": "2330", "kind": "service", "label": "無塵室與機電工程"},
        {"from": "3587", "to": "2330", "kind": "service", "label": "材料與故障分析"},
        {"from": "3587", "to": "2454", "kind": "service", "label": "晶片除錯與驗證"},
        {"from": "3443", "to": "demand", "kind": "service", "label": "自研 AI ASIC 設計與量產"},
        {"from": "NVDA-US", "to": "demand", "kind": "product", "label": "GPU 與 AI 系統"},
        {"from": "rack", "to": "demand", "kind": "product", "label": "機櫃建置"},
        {"from": "2454", "to": "market", "kind": "product", "label": "手機與消費性晶片"},
        {"from": "2408", "to": "market", "kind": "product", "label": "標準型 DRAM"},
    ],
},)

def members(version: dict) -> list[dict]:
    return [dict(code=code, company_name=name, segment=segment, significance=significance)
            for layer in version["layers"] for stage in layer["stages"]
            for code, name, segment, _role, significance in stage["companies"]]


def definition(version: dict) -> dict:
    """What a reader needs to draw the line-up: rows, the stages in each, and who feeds whom."""
    return {
        "layers": [{
            "key": layer.get("key", f"layer{index}"), "title": layer["title"],
            "stages": [{"title": stage["title"], "companies": [
                dict(code=code, company_name=name, segment=segment, role=role)
                for code, name, segment, role, _significance in stage["companies"]
            ]} for stage in layer["stages"]],
        } for index, layer in enumerate(version["layers"])],
        "flows": version["flows"],
        "links": version.get("links", []),
        "terminals": version.get("terminals", []),
    }
