---
title: "ansible"
publishDate: "2025-01-08 13:00:00"
img: /tymultiverse/assets/ansible.png
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/01/08
category: DevOps
tags:
  - Ansible
---

# Ansible Overview

## Introduction

Ansible 採用無代理架構，適用於伺服器及雲端環境的配置和管理。

## Key Components

### Ansible Agentless

- 透過 SSH（或 WinRM）進行管理。

### Ansible Automation Controller (AAC)

- 基於角色的存取控制
- 應用程式和配置的部署

### Ansible Automation Hub

- 中央儲存庫：存放模組與插件

### Event-Driven Ansible

事件驅動型 Ansible 包含三個部分：
1. Sources：事件來源
2. Rules：定義觸發動作的規則
3. Actions：執行的任務

## 附加概念

### 建立 Host

支援方式：
- SSH：Linux 系統
- WinRM：Windows 系統
- IP 清單：IP 地址管理

*密碼等敏感資訊應透過 Ansible Vault 保管。*

### Template 管理

管理項目：
- 機密資訊
- 憑證檔案
- 外部參數

### Job Launch vs Template Launch

- Job Launch：啟動任務，無法動態更新變數
- Template Launch：可更新動態變數

### Playbooks, Tasks & Modules

- Playbook：定義任務的配置文件
- Task：單一操作，對應 Ansible 模組
- Module：完成任務的基本單位



## 進階應用與最佳實踐

- Ansible Galaxy：社群分享的角色及模組
- 錯誤排除：檢查 SSH 配置與模組版本
- 安全管理：使用 Ansible Vault 加密敏感資料

## 參考資源

- [Ansible 官方文件](https://docs.ansible.com/)
- [Ansible Galaxy](https://galaxy.ansible.com/)
- [最佳實踐與範例](https://www.ansible.com/resources/get-started)