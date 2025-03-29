import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from io import BytesIO

# 定义一个辅助函数，根据预期字段判断使用哪一行作为表头
def load_excel_file(file, expected_fields, max_try=5):
    """
    尝试使用前 max_try 行作为表头来读取Excel文件，
    直到在某一行中发现至少有一个预期字段为止。
    如果都找不到，则默认使用第一行作为表头。
    
    参数：
        file: 上传的文件对象
        expected_fields: 预期必须存在的字段列表
        max_try: 尝试的最大行数（默认5行）
    返回：
        读取到的 DataFrame
    """
    for header_row in range(max_try):
        file.seek(0)  # 重置文件指针
        df = pd.read_excel(file, header=header_row)
        if set(expected_fields).intersection(df.columns):
            return df
    file.seek(0)
    return pd.read_excel(file, header=0)

# 示例预期字段（可根据你的实际情况调整）
expected_order_fields = ["姓名", "电话", "性别", "收货地址", "商品名称", "数量", "单价", "实际支付", "支付时间", "订单状态", "用户分组"]
expected_price_fields = ["sku名称", "单价", "服务类型"]

# ==========================
# 1. 文件上传与数据加载
# ==========================
orders_file = st.file_uploader("上传【商品订单】文件 (Excel 或 CSV)", type=['xlsx', 'xls', 'csv'])
price_file = st.file_uploader("上传【洗衣价格模板】文件 (Excel 或 CSV)", type=['xlsx', 'xls', 'csv'])

df_orders = pd.DataFrame()
df_price = pd.DataFrame()

if orders_file and price_file:
    st.write("正在读取商品订单文件...")
    try:
        if orders_file.name.lower().endswith('.csv'):
            df_orders = pd.read_csv(orders_file)
        else:
            df_orders = load_excel_file(orders_file, expected_order_fields)
    except Exception as e:
        orders_file.seek(0)
        df_orders = pd.read_excel(orders_file, header=1)
    
    if '订单号' not in df_orders.columns:
        st.warning("在商品订单文件中未找到“订单号”列，可能需要进一步调整表头或改列名。")
    st.write("商品订单文件表头:", df_orders.columns.tolist())
    
    st.write("正在读取洗衣价格模板文件...")
    try:
        if price_file.name.lower().endswith('.csv'):
            df_price = pd.read_csv(price_file)
        else:
            df_price = load_excel_file(price_file, expected_price_fields)
    except Exception as e:
        price_file.seek(0)
        df_price = pd.read_excel(price_file, header=1)
    
    if 'sku名称' not in df_price.columns:
        st.warning("在洗衣价格模板文件中未找到“sku名称”列，可能需要进一步调整表头或改列名。")
    st.write("洗衣价格模板文件表头:", df_price.columns.tolist())
    
    st.success("文件上传并读取完成！")

    # ================================
    # 2. 数据预处理与字段校验
    # ================================
    if not df_orders.empty:
        if '订单状态' in df_orders.columns:
            df_orders = df_orders[df_orders['订单状态'] == '已完成']
        if '实际支付' in df_orders.columns:
            df_orders = df_orders[df_orders['实际支付'] > 0]
        df_orders = df_orders.reset_index(drop=True)
    
    # 构建“单位-洗衣服务项”映射字典，依据洗衣价格模板中“服务类型”
    service_items_by_type = {}
    if not df_price.empty and '服务类型' in df_price.columns:
        for service_type, group_df in df_price.groupby('服务类型'):
            service_items_by_type[service_type] = [
                (str(row.get('sku名称','')), float(row.get('单价',0))) for _, row in group_df.iterrows()
            ]

    # =============================================
    # 3. 性别消费品目规则及界面可视化设置
    # =============================================
    if not df_price.empty and 'sku名称' in df_price.columns:
        all_item_names = sorted({ str(name) for name in df_price['sku名称'].dropna().unique() })
    else:
        all_item_names = []
    
    # 默认规则：包含“裙”或“女”的归为女性专用，包含“男”的归为男性专用
    female_only_defaults = [name for name in all_item_names if ('裙' in name or '女' in name) and ('男' not in name)]
    male_only_defaults   = [name for name in all_item_names if ('男' in name) and ('女' not in name)]
    
    st.subheader("性别消费品目配置")
    female_only = st.multiselect("限定女性使用的消费品目：", all_item_names, default=female_only_defaults)
    male_only = st.multiselect("限定男性使用的消费品目：", all_item_names, default=male_only_defaults)
    female_only_set = set(female_only)
    male_only_set   = set(male_only)
    
    st.markdown("---")
    st.subheader("订单转换处理")

    # ======================================
    # 4. 订单转换核心逻辑实现（优化版）
    # ======================================
    # 优化点：将回溯算法改为动态规划加缓存，提高组合计算速度
    def find_item_combo(items, target_cents):
        """
        items: [(item_name, price_cents), ...]
        target_cents: 目标金额（分）
        返回 (combo_list, best_sum)
        combo_list: [(item_name, qty), ...]
        best_sum: 凑到的总金额（分）， <= target_cents
        """
        memo = {}
        def dp(i, remaining):
            if remaining == 0:
                return ([], 0)
            if i == len(items):
                return ([], 0)
            if (i, remaining) in memo:
                return memo[(i, remaining)]
            best_combo, best_sum = [], 0
            # 尝试 0~3 个当前服务项
            for qty in range(0, 4):
                cost = items[i][1] * qty
                if cost > remaining:
                    break
                sub_combo, sub_sum = dp(i + 1, remaining - cost)
                current_sum = cost + sub_sum
                if current_sum > best_sum:
                    best_sum = current_sum
                    best_combo = []
                    if qty > 0:
                        best_combo.append((items[i][0], qty))
                    best_combo.extend(sub_combo)
                if best_sum == target_cents:
                    break
            memo[(i, remaining)] = (best_combo, best_sum)
            return memo[(i, remaining)]
        return dp(0, target_cents)

    output_rows = []
    logs = []
    new_order_counter = 1
    
    if not df_orders.empty:
        progress_bar = st.progress(0)
        total_orders = len(df_orders)
    
    with st.spinner("正在转换订单，请稍候..."):
        for idx, order in df_orders.iterrows():
            orig_id = str(order.get('订单号', ''))
            name = order.get('姓名', '')
            phone = str(order.get('电话', ''))
            gender = order.get('性别', '')
            user_group = order.get('用户分组', '')
            address = order.get('收货地址', '')
            pay_time = order.get('支付时间', '')
            
            # 根据商品订单的“用户分组”匹配洗衣服务（“服务类型”）
            if user_group not in service_items_by_type:
                logs.append(f"[失败] 原订单 {orig_id}: 无法匹配到服务类型 '{user_group}'")
                continue
            
            all_items = service_items_by_type[user_group]
            items_cents = []
            for item_name, price in all_items:
                # 性别过滤：男性订单不使用女性专用项，女性订单不使用男性专用项
                if gender == '男' and item_name in female_only_set:
                    continue
                if gender == '女' and item_name in male_only_set:
                    continue
                price_cents = int(round(price * 100))
                items_cents.append((item_name, price_cents))
            
            if not items_cents:
                logs.append(f"[失败] 原订单 {orig_id}: 无可用洗衣服务项（性别限制导致）")
                continue
            
            # 金额拆分：若订单金额大于300元，进行拆分
            import random

            def random_split(total_cents, max_per=30000, min_per=20000):
                """
                随机拆分总金额total_cents为多个子订单，
                每笔子订单金额介于min_per和max_per之间，
                保证所有子订单总和等于total_cents。
                """
                parts = []
                remaining = total_cents
                # 当剩余金额大于上限时，随机生成一个金额
                while remaining > max_per:
                    # 计算保证后续至少能拆出一个min_per的金额
                    max_possible = min(max_per, remaining - min_per)
                    # 如果剩余金额非常接近max_per，则直接用max_per
                    if max_possible < min_per:
                        part = remaining
                    else:
                        part = random.randint(min_per, max_possible)
                    parts.append(part)
                    remaining -= part
                if remaining > 0:
                    parts.append(remaining)
                return parts

            # 在订单转换部分替换固定拆分的代码：
            total_amount = float(order.get('实际支付', 0))
            total_cents = int(round(total_amount * 100))
            if total_amount > 300:
                # 使用随机拆分方式，设定下限为200元（20000分），上限为300元（30000分）
                sub_amounts = random_split(total_cents, max_per=30000, min_per=20000)
            else:
                sub_amounts = [total_cents]
                
            try:
                orig_datetime = pd.to_datetime(pay_time) if pay_time else datetime.now()
            except:
                orig_datetime = datetime.now()
            
            sub_index = 0
            success = True
            
            for sub_cents in sub_amounts:
                sub_index += 1
                combo, used_sum = find_item_combo(items_cents, sub_cents)
                if combo is None:
                    combo = []
                    used_sum = 0
                remainder = sub_cents - used_sum
                if remainder > 0:
                    combo.append(("补差服务", 1))
                    used_sum = sub_cents
                
                total_check = 0.0
                for item_name, qty in combo:
                    if item_name == "补差服务":
                        price = remainder / 100.0
                    else:
                        price = next((p for (n, p) in service_items_by_type[user_group] if n == item_name), 0.0)
                    total_check += price * qty
                total_check = round(total_check, 2)
                if abs(total_check - (sub_cents / 100.0)) > 1e-6:
                    success = False
                    logs.append(f"[失败] 原订单 {orig_id}: 第{sub_index}子单金额不匹配(应¥{sub_cents/100.0:.2f})")
                
                new_order_id = str(2503270000000000000 + new_order_counter)
                new_order_counter += 1
                sub_datetime = orig_datetime + timedelta(days=(sub_index - 1))
                order_time_str = sub_datetime.strftime("%Y-%m-%d %H:%M:%S")
                
                first_item = True
                for item_name, qty in combo:
                    if item_name == "补差服务":
                        unit_price = remainder / 100.0
                    else:
                        unit_price = next((p for (n, p) in service_items_by_type[user_group] if n == item_name), 0.0)
                    row = {
                        "新订单号": new_order_id if first_item else "",
                        "原订单号": orig_id if first_item else "",
                        "姓名": name if first_item else "",
                        "电话": phone if first_item else "",
                        "性别": gender if first_item else "",
                        "收货地址": address if first_item else "",
                        "单位名称": user_group if first_item else "",
                        "消费品目": item_name,
                        "数量": qty,
                        "单价": f"{unit_price:.2f}",
                        "实际支付": f"{(sub_cents/100):.2f}" if first_item else "",
                        "订单状态": "已完成" if first_item else "",
                        "下单时间": order_time_str if first_item else ""
                    }
                    output_rows.append(row)
                    first_item = False
            
            if success:
                logs.append(f"[成功] 原订单 {orig_id}: 转换完成，生成 {len(sub_amounts)} 笔洗衣订单")
            else:
                logs.append(f"[警告] 原订单 {orig_id}: 存在金额不匹配或补差服务处理")
            progress_bar.progress((idx + 1) / total_orders)
    
    # ======================================
    # 5. 预览转换结果及导出下载
    # ======================================
    if output_rows:
        output_df = pd.DataFrame(output_rows)
        st.subheader("转换结果预览（前10条记录）")
        st.dataframe(output_df.head(10))
        
        st.subheader("转换日志")
        for msg in logs:
            if msg.startswith("[成功]"):
                st.success(msg)
            elif msg.startswith("[失败]"):
                st.error(msg)
            elif msg.startswith("[警告]"):
                st.warning(msg)
            else:
                st.info(msg)
        
        # 下载 CSV
        csv_data = output_df.to_csv(index=False).encode('utf-8')
        
        # 下载 Excel
        def to_excel(df):
            out = BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='洗衣订单')
            return out.getvalue()
        
        excel_data = to_excel(output_df)
        
        st.download_button(
            label="下载转换结果 CSV",
            data=csv_data,
            file_name="转换后洗衣订单.csv",
            mime="text/csv"
        )
        st.download_button(
            label="下载转换结果 Excel",
            data=excel_data,
            file_name="转换后洗衣订单.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        if orders_file and price_file:
            st.warning("未生成任何洗衣订单。请检查是否有符合条件的订单数据，或查看日志信息。")