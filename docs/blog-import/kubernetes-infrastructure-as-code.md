---
title: "kubernetes-infrastructure-as-code"
publishDate: "2024-12-26 13:00:00"
img: /tymultiverse/assets/k8s.png
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/12/26
level: advance
category: Kubernetes
tags:
  - Kubernetes
  - Infrastructure as Code
---

# Kubernetes Infrastructure as Code (IaC)

## Overview

Infrastructure as Code (IaC) 實現了基礎架構的自動化配置和管理，特別適用於 Kubernetes 集群環境。本文著重介紹 Kubernetes 中的 IaC 實踐，並說明 Cloud Controller Manager（CCM）的核心角色。

## Cloud Controller Manager (CCM)

CCM 為 Kubernetes 提供雲端相關功能，主要特性包括：

1. **節點 Label 加入**：透過標籤告知虛擬機當前任務。  
2. **儲存空間整合**：將儲存資源的 id 與 Kubernetes 物件進行對應。  
3. **節點資訊注入**：在 node YAML 中嵌入虛擬機相關資訊。

