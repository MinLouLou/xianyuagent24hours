const SERVER = "http://43.156.81.25:8899";

function setStatus(type, text) {
  const box = document.getElementById("statusBox");
  box.className = "status-box " + type;
  document.getElementById("statusText").textContent = text;
}

// 启动时加载账号列表，并绑定按钮事件
document.addEventListener("DOMContentLoaded", () => {
  loadAccounts();
  document.getElementById("syncBtn").addEventListener("click", syncCookie);
});

async function loadAccounts() {
  const select = document.getElementById("accountSelect");
  const btn = document.getElementById("syncBtn");

  try {
    const resp = await fetch(`${SERVER}/accounts`);
    const data = await resp.json();

    select.innerHTML = '<option value="">-- 请选择账号 --</option>';
    data.accounts.forEach(acc => {
      const opt = document.createElement("option");
      opt.value = acc.name;
      opt.textContent = acc.enabled ? `${acc.name} ✅` : `${acc.name} （未启用）`;
      select.appendChild(opt);
    });

    select.addEventListener("change", () => {
      btn.disabled = !select.value;
      if (select.value) {
        setStatus("", `已选择账号：${select.value}`);
      }
    });

    setStatus("", "请选择账号后点击同步");

  } catch (e) {
    select.innerHTML = '<option value="">无法连接本地服务</option>';
    setStatus("error", "请先启动 cookie_server.py");
  }
}

async function syncCookie() {
  const accountName = document.getElementById("accountSelect").value;
  const btn = document.getElementById("syncBtn");

  if (!accountName) {
    setStatus("error", "请先选择账号");
    return;
  }

  btn.disabled = true;
  setStatus("loading", `正在提取 ${accountName} 的 Cookie...`);

  try {
    // 获取 goofish.com 的所有 Cookie
    const [c1, c2] = await Promise.all([
      chrome.cookies.getAll({ domain: "goofish.com" }),
      chrome.cookies.getAll({ domain: ".goofish.com" }),
    ]);

    const allCookies = [...c1, ...c2];

    if (allCookies.length === 0) {
      setStatus("error", "未找到 Cookie，请先在 goofish.com 登录");
      btn.disabled = false;
      return;
    }

    // 去重并拼接为 cookie 字符串
    const seen = new Set();
    const cookieStr = allCookies
      .filter(c => { if (seen.has(c.name)) return false; seen.add(c.name); return true; })
      .map(c => `${c.name}=${c.value}`)
      .join("; ");

    setStatus("loading", `正在同步到账号 [${accountName}]...`);

    const resp = await fetch(`${SERVER}/update-cookie`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_name: accountName, cookie: cookieStr }),
    });

    const result = await resp.json();

    if (result.success) {
      setStatus("success", `✅ [${accountName}] 同步成功，机器人重启中`);
    } else {
      setStatus("error", "失败：" + (result.message || "未知错误"));
    }

  } catch (err) {
    if (err.message && err.message.includes("Failed to fetch")) {
      setStatus("error", "连接失败：请先启动 cookie_server.py");
    } else {
      setStatus("error", "错误：" + err.message);
    }
  }

  btn.disabled = false;
}
