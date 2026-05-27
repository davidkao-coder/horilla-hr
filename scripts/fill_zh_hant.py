"""Fill the 80+ remaining untranslated msgids in horilla/locale/zh_Hant/LC_MESSAGES/django.po."""

import re
from pathlib import Path

PO_PATH = Path(__file__).resolve().parent.parent / "horilla" / "locale" / "zh_Hant" / "LC_MESSAGES" / "django.po"

TRANSLATIONS = {
    "Assign asset before adding a report": "請先指派資產，再新增報告",
    "Invalid list of IDs provided.": "提供的 ID 清單無效。",
    "Failed to delete attendance activities: {error}": "刪除出勤紀錄失敗：{error}",
    "Your department was mentioned in an announcement.": "您的部門在公告中被提及。",
    "Your job position was mentioned in an announcement.": "您的職位在公告中被提及。",
    "You have been mentioned in an announcement.": "您在公告中被提及。",
    "By enabling this the display name will take from who triggered the mail": "啟用後，寄件人顯示名稱將採用觸發郵件的人員",
    "Show Comments to All": "顯示留言給所有人",
    "If enabled, all employees can view each other's comments.": "啟用後，所有員工均可查看彼此的留言。",
    "Only one TrackLateComeEarlyOut instance is allowed.": "僅允許一筆遲到早退追蹤設定。",
    "Enter the OTP send to your email: ": "請輸入寄送至您信箱的 OTP：",
    "Resend OTP in": "重新傳送 OTP 倒數",
    "task-all": "全部任務",
    "backup": "備份",
    "gdrive": "Google 雲端硬碟",
    "horilla-theme": "Horilla 主題",
    "leave-report": "請假報表",
    "Profile edit accessibility feature has been removed.": "個人資料編輯的便利存取功能已移除。",
    "This biometric %(label)s is already mapped with an employee": "此生物辨識 %(label)s 已對應到員工",
    "e-Time Office": "e-Time Office 系統",
    "Alternate In/Out Device": "備援上下班裝置",
    "System Direction(In/Out) Device": "系統判定方向（上/下班）裝置",
    "Fetch Logs": "取得日誌",
    "Dahua User": "大華使用者",
    "Map Dahua User": "對應大華使用者",
    "Double-check the provided IP, Port, and Password.": "請再次確認提供的 IP、連接埠與密碼。",
    "API credentials might be incorrect.": "API 憑證可能不正確。",
    "Double-check the provided Machine IP, Username, and Password.": "請再次確認提供的機器 IP、使用者名稱與密碼。",
    "Double-check the provided API Url, Username, and Password: {}": "請再次確認提供的 API 網址、使用者名稱與密碼：{}",
    "Double-check the provided API Url, Username, and Password": "請再次確認提供的 API 網址、使用者名稱與密碼",
    "No rows are selected for deleting users from device.": "未選取要從裝置刪除的使用者資料列。",
    "The uploaded file is empty, Not contain records.": "上傳的檔案為空，未包含任何資料。",
    "These required headers are missing in the uploaded file: ": "上傳的檔案缺少下列必要欄位：",
    "Write": "寫入",
    "No IDs provided.": "未提供 ID。",
    "Unsupported file format. Please upload a CSV or Excel file.": "不支援的檔案格式，請上傳 CSV 或 Excel 檔。",
    "Load Faqs": "載入常見問題",
    "No FAQ found for the given category.": "此分類下沒有常見問題。",
    "Negative value is not accepatable.": "不接受負數值。",
    "Enter a hour between 0 to 24.": "請輸入 0 到 24 之間的小時數。",
    "Enter a minute between 0 to 60.": "請輸入 0 到 60 之間的分鐘數。",
    "gdrive backup automation setup updated.": "Google 雲端硬碟備份自動化設定已更新。",
    "gdrive backup automation setup Created.": "Google 雲端硬碟備份自動化設定已建立。",
    "LDAP to Horilla Employee Field Mapping": "LDAP 與 Horilla 員工欄位對應",
    "LDAP Attribute Name": "LDAP 屬性名稱",
    "LDAP Object Class": "LDAP 物件類別",
    "e.g., inetOrgPerson": "例如：inetOrgPerson",
    "Feature is not enabled on the settings": "此功能尚未在設定中啟用",
    "Invalid date format. Please use YYYY-MM-DD or a supported format.": "日期格式錯誤，請使用 YYYY-MM-DD 或其他支援的格式。",
    "No Assets Due for Return from Offboarding Employees.": "離職員工目前無待歸還的資產。",
    "Exit Ratio": "離職比率",
    "Archived Employees / Total Employees": "封存員工數 / 員工總數",
    "Exiting to Joining Ratio": "離職與入職比率",
    "Exiting Employees : Joining Employees": "離職員工 : 入職員工",
    "Joining and Offboarding Chart": "入職與離職圖表",
    "No Pending Tasks for Offboarding Employees.": "離職員工沒有待處理的任務。",
    "Primary": "主要",
    "Refresh Token": "更新權杖",
    "Token not refreshed, Login required": "權杖未更新，需要重新登入",
    "Outlook authentication required/expired": "Outlook 驗證需要進行或已過期",
    "Employees need to sent feedback request.": "需要傳送回饋邀請的員工。",
    "Employees for whom the feedback requester is the reporting manager": "由回饋發送者作為直屬主管的員工",
    "Time Sheet": "工時表",
    "Time Sheets": "工時表",
    "Time sheet": "工時表",
    "View Timesheet Chart": "查看工時表圖表",
    " Time sheet": " 工時表",
    "Time Spent": "花費時間",
    "Could not retrieve project IDs.": "無法取得專案 ID。",
    "Invalid value for 'is_active'. Use 'true' or 'false'.": "「is_active」的值無效，請使用 'true' 或 'false'。",
    "Permission denied or skipped for: %(projects)s.": "下列專案權限不足或已略過：%(projects)s。",
    "{} tasks.": "{} 個任務。",
    "Can't Delete. This stage contain some tasks": "無法刪除，此階段內仍有任務",
    "LinkedIn account is required for publishing.": "發佈時必須提供 LinkedIn 帳號。",
    "Post on LinkedIn": "發佈至 LinkedIn",
    "Accepted": "已接受",
    "Joined": "已加入",
    "Email mismatched.": "電子郵件不一致。",
    "Check the credentials": "請檢查憑證",
    "Check Connection": "檢查連線",
    "LinkedIn connection success.": "LinkedIn 連線成功。",
    "LinkedIn connection failed.": "LinkedIn 連線失敗。",
    "The recruitment entry you are trying to edit does not exist.": "您要編輯的招募項目不存在。",
    "Geo & Face Config": "地理位置與臉部辨識設定",
}


def main() -> None:
    src = PO_PATH.read_text(encoding="utf-8")
    blocks = src.split("\n\n")
    out_blocks = []
    filled = 0
    misses = []

    for idx, block in enumerate(blocks):
        if idx == 0:
            out_blocks.append(block)
            continue

        # Parse msgid (may be multi-line) and msgstr
        msgid_match = re.search(r'msgid "(.*?)"\n(?!")', block, re.DOTALL)
        msgstr_match = re.search(r'msgstr "(.*?)"(\n|$)', block, re.DOTALL)
        if not (msgid_match and msgstr_match):
            out_blocks.append(block)
            continue

        msgid = msgid_match.group(1)
        msgstr = msgstr_match.group(1)

        if msgstr == "" and msgid != "":
            if msgid in TRANSLATIONS:
                replacement = TRANSLATIONS[msgid].replace('"', '\\"')
                new_block = block.replace(
                    f'msgstr ""',
                    f'msgstr "{replacement}"',
                    1,
                )
                out_blocks.append(new_block)
                filled += 1
                continue
            else:
                misses.append(msgid)

        out_blocks.append(block)

    PO_PATH.write_text("\n\n".join(out_blocks), encoding="utf-8")
    print(f"Filled: {filled}")
    if misses:
        print(f"Still untranslated ({len(misses)}):")
        for m in misses[:50]:
            print(f"  - {m!r}")


if __name__ == "__main__":
    main()
