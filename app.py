import streamlit as st
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from PIL import Image
import json
import io
from datetime import datetime


# --- 頁面基本設定 ---
st.set_page_config(page_title="AI 名片掃描器", page_icon="📇")
# st.write("目前讀到的 Secrets:", st.secrets)

# --- 1. 定義 Gemini AI 功能 ---
def get_gemini_response(image_bytes):
    try:
        # 從 Secrets 讀取 API Key
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        
        # 使用 Gemini 1.5 Flash (速度快、免費額度高)
        model = genai.GenerativeModel(
            model_name="models/gemini-2.5-flash",
            generation_config={"response_mime_type": "application/json"} # 強制回傳 JSON
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
        # 捕捉免費額度用完的錯誤 (HTTP 429)
        if "429" in error_msg or "ResourceExhausted" in error_msg:
            return "QUOTA_EXCEEDED"
        else:
            st.error(f"AI 系統錯誤: {error_msg}")
            return None

# --- 2. 定義 Google Sheets 寫入功能 ---
def save_to_google_sheets(data, note):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        # 從 Secrets 讀取服務帳號設定
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        # 開啟試算表
        sheet_url = st.secrets["SHEET_URL"]
        sheet = client.open_by_url(sheet_url).sheet1
        
        # 計算項次
        existing_data = sheet.get_all_values()
        next_index = len(existing_data) if len(existing_data) > 0 else 1
        
        upload_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 準備寫入的資料列
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

# --- 3. 建置網頁介面 ---
st.title("📇 AI 名片掃描器")
st.caption("Powered by Gemini 1.5 Flash")

col1, col2 = st.columns([1, 1])

with col1:
    st.info("步驟 1：拍攝或上傳")
    picture = st.camera_input("拍攝名片")
    # 如果想支援上傳圖片，可自行解開下行註解
    uploaded_file = st.file_uploader("或上傳圖片", type=['jpg', 'png']) 
    
    st.info("步驟 2：新增備註")
    user_note = st.text_input("輸入備註", placeholder="例：展覽認識的客戶...")

with col2:
    st.info("步驟 3：AI 處理")
    if picture:
        if st.button("🚀 開始辨識並存檔", type="primary"):
            with st.spinner("AI 正在讀取名片..."):
                image_bytes = picture.getvalue()
                
                # 1. 呼叫 AI
                result = get_gemini_response(image_bytes)
                
                # 2. 判斷結果
                if result == "QUOTA_EXCEEDED":
                    st.error("⚠️ 免費版額度已用完 (HTTP 429)，請稍後再試！")
                elif result:
                    st.success("辨識成功！")
                    st.json(result) # 顯示結果供核對
                    
                    # 3. 存入表格
                    if save_to_google_sheets(result, user_note):
                        st.balloons()
                        st.success("✅ 資料已成功寫入 Google Sheets")
    else:
        st.warning("請先在左側拍攝照片")
