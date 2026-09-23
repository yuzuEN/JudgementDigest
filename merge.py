import pandas as pd
import re

files_prefix = 'judgments_ADV_TPD_M_'
files_suffix = ['20260914_222828.xlsx', '20260914_050629.xlsx']
final_name = '25_07-12.xlsx'
result = pd.DataFrame()

for file_suffix in files_suffix:
    file_path = files_prefix + file_suffix
    df = pd.read_excel(file_path)
    
    
    result = pd.concat([result, df], ignore_index=True)
    result.drop_duplicates(subset=['裁判書連結'], keep='first', inplace=True)
    
    
result.to_excel(final_name, index=False, sheet_name = '裁判書資料')

print("總筆數：" , len(result))