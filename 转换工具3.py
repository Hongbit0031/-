import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from io import BytesIO
import random

if 'cached_price_df' not in st.session_state:
    st.session_state['cached_price_df'] = None

st.set_page_config(page_title="洗衣订单转换工具", layout="centered")  # 页面配置

# 标题
st.title("洗衣订单转换工具")
st.write("请按照步骤上传文件并配置选项，然后点击 **开始转换** 按钮执行转换。")

# 1. 文件上传
orders_file = st.file_uploader("📦 上传商品订单文件（支持 Excel / CSV，大小上限 200MB）", type=['xlsx', 'xls', 'csv'], label_visibility="visible")
price_file = st.file_uploader("🧺 上传洗衣价格模板文件（支持 Excel / CSV，大小上限 200MB）", type=['xlsx', 'xls', 'csv'], label_visibility="visible")

# 上传成功提示和文件名显示
if orders_file is not None:
    st.success(f"商品订单文件 **{orders_file.name}** 上传成功")
    # 可选预览商品订单数据
    with st.expander("查看商品订单文件内容", expanded=False):
        try:
            if orders_file.name.lower().endswith('.csv'):
                df_preview = pd.read_csv(orders_file)
            else:
                df_preview = pd.read_excel(orders_file)
        except Exception:
            orders_file.seek(0)
            df_preview = pd.read_excel(orders_file, header=1)
        st.dataframe(df_preview.head(5))
if price_file is not None:
    st.success(f"洗衣价格模板文件 **{price_file.name}** 上传成功")
    # 可选预览洗衣价格模板数据
    with st.expander("查看洗衣价格模板数据", expanded=False):
        try:
            if price_file.name.lower().endswith('.csv'):
                df_preview2 = pd.read_csv(price_file)
            else:
                df_preview2 = pd.read_excel(price_file)
        except Exception:
            price_file.seek(0)
            df_preview2 = pd.read_excel(price_file, header=1)
        st.dataframe(df_preview2.head(5))

# 2. 数据读取与处理（在两个文件都上传后进行）
df_orders = pd.DataFrame()
df_price = pd.DataFrame()
if orders_file is not None and price_file is not None:
    # 读取商品订单数据
    try:
        orders_file.seek(0)
        if orders_file.name.lower().endswith('.csv'):
            df_orders = pd.read_csv(orders_file)
        else:
            # 尝试自动检测表头行
            df_orders = pd.read_excel(orders_file, header=0)
            if not {"订单号", "姓名", "商品名称"}.intersection(df_orders.columns):
                # 如果第一行不是表头，则尝试第二行作为表头
                orders_file.seek(0)
                df_orders = pd.read_excel(orders_file, header=1)
    except Exception as e:
        st.error(f"读取商品订单文件时出错: {e}")
    # 读取洗衣价格模板数据
    try:
        price_file.seek(0)
        if price_file.name.lower().endswith('.csv'):
            df_price = pd.read_csv(price_file)
        else:
            df_price = pd.read_excel(price_file, header=0)
            if "sku名称" not in df_price.columns:
                price_file.seek(0)
                df_price = pd.read_excel(price_file, header=1)
        st.session_state['cached_price_df'] = df_price.copy()
    except Exception as e:
        st.error(f"读取洗衣价格模板文件时出错: {e}")
    
    # 简单字段校验提示
    if '订单号' not in df_orders.columns:
        st.warning("警告：商品订单文件中未找到“订单号”列，请确认表头是否正确。")
    if 'sku名称' not in df_price.columns:
        st.warning("警告：洗衣价格模板文件中未找到“sku名称”列，请确认表头是否正确。")
    
    # 过滤掉未完成或未支付的订单
    if not df_orders.empty:
        if '订单状态' in df_orders.columns:
            df_orders = df_orders[df_orders['订单状态'] == '已完成']
        if '实际支付' in df_orders.columns:
            df_orders = df_orders[df_orders['实际支付'] > 0]
        df_orders = df_orders.reset_index(drop=True)
    st.success("文件上传并读取完成，可进行转换设置。")
    
    # 3. 构建服务类型对应的洗衣服务项列表
    service_items_by_type = {}
    if not df_price.empty and '服务类型' in df_price.columns:
        for service_type, grp in df_price.groupby('服务类型'):
            items = []
            for _, row in grp.iterrows():
                name = str(row.get('sku名称', ''))
                price = float(row.get('单价', 0))
                if name:
                    items.append((name, price))
            service_items_by_type[service_type] = items
    
    # 获取所有消费品目名称列表用于配置
    all_item_names = sorted({str(n) for n in df_price['sku名称'].dropna().unique()}) if 'sku名称' in df_price.columns else []
    # 默认性别限定品目集合
    female_only_defaults = [n for n in all_item_names if ('裙' in n or '女' in n) and '男' not in n]
    male_only_defaults   = [n for n in all_item_names if '男' in n and '女' not in n]
    
    # 4. 自定义配置选项（默认折叠）
    with st.expander("自定义配置选项", expanded=False):
        st.markdown("**性别消费品目限制**")
        female_only = st.multiselect("限定女性使用的消费品目：", all_item_names, default=female_only_defaults)
        male_only   = st.multiselect("限定男性使用的消费品目：", all_item_names, default=male_only_defaults)
        female_only_set = set(female_only)
        male_only_set = set(male_only)
        st.markdown("**金额拆分设置**")
        max_split_amount = st.number_input("最大拆单金额 (元)：", min_value=1, value=300)
    
    # 5. 开始转换按钮
    convert_btn = st.button("开始转换")
    if convert_btn:
        # 转换逻辑执行
        output_rows = []
        logs = []
        new_order_counter = 1
        total_orders = len(df_orders)
        # 进度指示
        progress_text = "转换进度: 0%"
        progress_bar = st.progress(0, text=progress_text)
        # Spinner提示
        with st.spinner("正在转换订单，请稍候..."):
            for idx, order in df_orders.iterrows():
                orig_id = str(order.get('订单号', ''))
                name    = order.get('姓名', '')
                phone   = str(order.get('电话', ''))
                gender  = order.get('性别', '')
                user_group = order.get('用户分组', '')
                address = order.get('收货地址', '')
                pay_time = order.get('支付时间', '')
                
                # 根据用户分组确定服务类型
                if user_group not in service_items_by_type:
                    logs.append(f"[失败] 原订单 {orig_id}: 找不到匹配的服务类型 “{user_group}”")
                    continue
                all_items = service_items_by_type[user_group]
                
                # 按性别过滤可用消费品目
                items_cents = []
                for item_name, price in all_items:
                    if gender == '女' and item_name in male_only_set:
                        continue  # 女性订单排除男性限定品目
                    if gender == '男' and item_name in female_only_set:
                        continue  # 男性订单排除女性限定品目
                    price_cents = int(round(price * 100))
                    items_cents.append((item_name, price_cents))
                if not items_cents:
                    logs.append(f"[失败] 原订单 {orig_id}: 无可用的洗衣服务项（可能因性别限制）")
                    continue
                
                # 订单金额拆分
                total_amount = float(order.get('实际支付', 0))
                total_cents = int(round(total_amount * 100))
                max_per = int(max_split_amount * 100)  # 用户设定的最大单笔金额（分）

                if total_cents > max_per:
                    # 递归拆分函数，将总金额随机拆成两份
                    def recursive_split(amount, max_per):
                        if amount <= max_per:
                            return [amount]
                        else:
                            part1 = random.randint(1, amount - 1)
                            part2 = amount - part1
                            return recursive_split(part1, max_per) + recursive_split(part2, max_per)
                    sub_amounts = recursive_split(total_cents, max_per)
                else:
                    sub_amounts = [total_cents]
                
                # 转换每个子订单
                try:
                    orig_datetime = pd.to_datetime(pay_time) if pay_time else datetime.now()
                except:
                    orig_datetime = datetime.now()
                success = True
                for sub_index, sub_cents in enumerate(sub_amounts, start=1):
                    # 找到最接近子单金额的服务项组合
                    def find_item_combo(items, target):
                        # 动态规划寻找 <= target 的最大组合
                        memo = {}
                        def dp(i, remaining):
                            if remaining == 0 or i == len(items):
                                return [], 0
                            if (i, remaining) in memo:
                                return memo[(i, remaining)]
                            best_combo, best_sum = [], 0
                            # 尝试0~3件第i项
                            item_name, price = items[i]
                            for qty in range(0, 4):
                                cost = price * qty
                                if cost > remaining:
                                    break
                                sub_combo, sub_sum = dp(i+1, remaining - cost)
                                current_sum = cost + sub_sum
                                if current_sum > best_sum:
                                    best_sum = current_sum
                                    best_combo = []
                                    if qty > 0:
                                        best_combo.append((item_name, qty))
                                    best_combo.extend(sub_combo)
                                # 如果正好匹配总额则提前结束
                                if best_sum == remaining:
                                    break
                            memo[(i, remaining)] = (best_combo, best_sum)
                            return memo[(i, remaining)]
                        return dp(0, target)
                    combo, used_sum = find_item_combo(items_cents, sub_cents)
                    # 计算未匹配金额作为“补差”
                    remainder = sub_cents - used_sum
                    if remainder > 0:
                        combo.append(("补差服务", 1))  # 剩余金额作为补差服务
                        used_sum = sub_cents
                    # 校验子订单金额是否吻合
                    total_check = 0.0
                    for item_name, qty in combo:
                        if item_name == "补差服务":
                            price_val = remainder / 100.0
                        else:
                            price_val = next((p for (n, p) in service_items_by_type[user_group] if n == item_name), 0.0)
                        total_check += price_val * qty
                    total_check = round(total_check, 2)
                    if abs(total_check - (sub_cents / 100.0)) > 1e-6:
                        success = False
                        logs.append(f"[失败] 原订单 {orig_id}: 第{sub_index}子单金额匹配误差")
                    # 生成新洗衣订单记录
                    new_order_id = str(2503270000000000000000000000 + new_order_counter)
                    new_order_counter += 1
                    sub_datetime = orig_datetime + timedelta(days=(sub_index - 1))
                    order_time_str = sub_datetime.strftime("%Y-%m-%d %H:%M:%S")
                    first_line = True
                    for item_name, qty in combo:
                        if item_name == "补差服务":
                            unit_price = remainder / 100.0
                        else:
                            unit_price = next((p for (n, p) in service_items_by_type[user_group] if n == item_name), 0.0)
                        output_rows.append({
                            "新订单号": new_order_id if first_line else "",
                            "原订单号": orig_id if first_line else "",
                            "姓名": name if first_line else "",
                            "电话": phone if first_line else "",
                            "性别": gender if first_line else "",
                            "收货地址": address if first_line else "",
                            "单位名称": user_group if first_line else "",
                            "消费品目": item_name,
                            "数量": qty,
                            "单价": f"{unit_price:.2f}",
                            "实际支付": f"{unit_price * qty:.2f}",
                            "订单总价": f"{sub_cents/100:.2f}" if first_line else "",
                            "订单状态": "已完成" if first_line else "",
                            "下单时间": order_time_str if first_line else ""
                        })
                        first_line = False
                # 日志记录
                if success:
                    logs.append(f"[成功] 原订单 {orig_id}: 转换完成，生成 {len(sub_amounts)} 笔洗衣订单")
                else:
                    logs.append(f"[警告] 原订单 {orig_id}: 已生成订单，但存在金额校验误差或补差")
                # 更新进度条
                percent = int((idx + 1) / total_orders * 100)
                progress_bar.progress(percent, text=f"转换进度: {percent}%")
        
        # 移除加载提示（spinner结束后自动）
        progress_bar.empty()  # 清空进度条组件（可选）
        
        # 6. 转换结果预览和日志
        if output_rows:
            output_df = pd.DataFrame(output_rows)
            st.subheader("转换结果预览（前10条记录）")
            st.dataframe(output_df.head(10))
            
            # 下载文件
            csv_data = output_df.to_csv(index=False).encode('utf-8')
            def to_excel_bytes(df):
                out = BytesIO()
                with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                    df.to_excel(writer, sheet_name="洗衣订单", index=False)
                return out.getvalue()
            excel_data = to_excel_bytes(output_df)
            st.download_button("下载转换结果 CSV", data=csv_data, file_name="转换后洗衣订单.csv", mime="text/csv")
            st.download_button("下载转换结果 Excel", data=excel_data, file_name="转换后洗衣订单.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.warning("未生成任何洗衣订单，请检查输入数据和日志信息。")
        
        # 日志信息反馈（默认折叠）
        with st.expander("转换日志", expanded=False):
            for msg in logs:
                if msg.startswith("[成功]"):
                    st.success(msg)
                elif msg.startswith("[失败]"):
                    st.error(msg)
                elif msg.startswith("[警告]"):
                    st.warning(msg)
                else:
                    st.info(msg)
