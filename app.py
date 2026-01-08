import streamlit as st
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from PIL import Image
import json
import io
from datetime import datetime

# --- 頁面基本設定 ---
st.set_page_config(page_title="貝拉的名片夾", page_icon="📇")

# --- 1. 定義 Gemini AI 功能 ---
def get_gemini_response(image_bytes):
    try:
        # 從 Secrets 讀取 API Key
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        
        # 使用最新的 Gemini 2.5 Flash
        model = genai.GenerativeModel(
            model_name="models/gemini-2.5-flash",
            generation_config={"response_mime_type": "application/json"}
        )

        prompt = """
        你是專業的名片辨識助理。請分析這張名片圖片，並提取以下資訊。
        請務必以嚴格的 JSON 格式回傳，key 必須完全符合下列名稱。
        若欄位在圖片中找不到，請回傳空字串 ""。
        
        需要的欄位：
        - chinese_name (中文姓名)
        - english_name (英文姓名)
        - department (部門)
        - title (職位)
        - mobile (手機)
        - phone (電話)
        - email (信箱)
        - address (公司地址)
        """

        image = Image.open(io.BytesIO(image_bytes))
        
        # 發送請求
        response = model.generate_content([prompt, image])
        return json.loads(response.text)

    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "ResourceExhausted" in error_msg:
            return "QUOTA_EXCEEDED"
        else:
            st.error(f"AI 系統錯誤: {error_msg}")
            return None

# --- 2. 定義 Google Sheets 寫入功能 ---
def save_to_google_sheets(data, note):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        sheet_url = st.secrets["SHEET_URL"]
        sheet = client.open_by_url(sheet_url).sheet1
        
        existing_data = sheet.get_all_values()
        next_index = len(existing_data) if len(existing_data) > 0 else 1
        
        upload_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        row = [
            next_index,
            data.get('chinese_name', ''),
            data.get('english_name', ''),
            data.get('department', ''),
            data.get('title', ''),
            data.get('mobile', ''),
            data.get('phone', ''),
            data.get('email', ''),
            data.get('address', ''),
            note,
            upload_time
        ]
        
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"資料庫連線失敗: {e}")
        return False

# --- 3. 建置網頁介面 (貝拉專屬版) ---
st.title("📇 貝拉的名片夾")

# 顯示提示訊息
st.info("💡 提示：使用「拍照」時請將手機橫向持握。若需翻轉鏡頭請按預覽畫面右上角圖示。")

# --- 步驟 1：選擇輸入方式 ---
st.subheader("步驟 1：取得名片影像")

# 建立選擇按鈕 (Radio Button)
input_method = st.radio("選擇輸入方式", ["📸 拍照", "📂 上傳圖片"], horizontal=True)

final_image = None  # 用來存放最終要處理的圖片

if input_method == "📸 拍照":
    camera_file = st.camera_input("點擊下方按鈕拍照", label_visibility="collapsed")
    if camera_file:
        final_image = camera_file

else: # 如果選的是上傳圖片
    upload_file = st.file_uploader("請上傳名片圖片", type=['jpg', 'jpeg', 'png'])
    if upload_file:
        st.image(upload_file, caption="預覽上傳圖片", width=300)
        final_image = upload_file

# --- 步驟 2：備註 ---
st.subheader("步驟 2：輸入備註")
user_note = st.text_input("輸入備註 (例如：展場認識、客戶興趣)", placeholder="選填...")

# --- 步驟 3：送出按鈕 (控制邏輯) ---
st.write("---") # 分隔線

# 送出按鈕
if st.button("🚀 送出辨識並存檔", type="primary", use_container_width=True):
    
    # 檢查有沒有圖片 (不管來源是拍照還是上傳)
    if final_image is None:
        st.warning("⚠️ 請先完成步驟 1 (拍照或上傳圖片)！")
        st.stop()
        
    with st.spinner("AI 正在讀取名片..."):
        # 取得圖片的 bytes 資料
        image_bytes = final_image.getvalue()
        
        # 1. 呼叫 AI
        result = get_gemini_response(image_bytes)
        
        # 2. 判斷結果
        if result == "QUOTA_EXCEEDED":
            st.error("⚠️ 免費版額度已用完，請稍後再試！")
        elif result:
            st.success("辨識成功！")
            
            # 顯示結果預覽
            with st.expander("查看辨識結果詳情"):
                st.json(result)
            
            # 3. 存入表格
            if save_to_google_sheets(result, user_note):
                st.balloons()
                st.success("✅ 資料已成功寫入 Google Sheets")