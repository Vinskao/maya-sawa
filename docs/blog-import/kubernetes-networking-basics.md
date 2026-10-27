---
title: "kubernetes-networking-basics"
publishDate: "2024-12-26 13:00:00"
img: /tymultiverse/assets/k8s.png
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/12/13
level: advance
category: Kubernetes
tags:
  - Kubernetes
  - Networking
---

# Kubernetes Networking

## Overview

本文從集群內部通訊與外部連線兩大方面，介紹 Kubernetes 中網絡架構的基本原理與組件，包括 kube-proxy、Service、Ingress 等，並探討網絡排查和安全策略。

## 內部網絡

### kube-proxy

`kube-proxy` 為 Kubernetes 提供虛擬網路，它負責監控 Service 變化，並動態調整轉發規則，以實現跨 Node 的流量分發。

### Pod 之間的連線

- **直接 IP 連線**：每個 Pod 都獲得一個獨立 IP，可直接通訊。  
- **Service 抽象**：將一組 Pod 整合為一個虛擬 IP，實現負載均衡。

## Service 物件

Service 提供穩定的網絡入口：

- **服務發現**：透過 Label Selector 動態選取後端 Pod。  
- **負載均衡**：將流量分發至各個 Pod。  
- 可設定為：
  - **ClusterIP**：僅內部訪問。
  - **NodePort**：每個 Node 對外開放固定端口。
  - **LoadBalancer**：自動配置外部負載均衡器。

## 進階網絡概念

### Ingress

Ingress 負責管理進入集群的 HTTP/HTTPS 流量，可以根據 host 和 path 規則進行流量轉發和 SSL Termination。

### EndpointSlice

EndpointSlice 對大量 Pod 的 Endpoints 進行分片管理，提升性能與可拓展性。

### Egress 與 Network Policies

- **Egress**：管理 Pod 外發連線，例如配置出口 IP。  
- **Network Policy**：定義限制進出流量的規則，以達到安全防護目的。

## 排查網絡問題

- **Layer 2 至 Layer 3**：確認資料鏈路層與網絡層之間的轉換是否正常。  
- **LB 異常**：檢查是否因後端服務或負載均衡器導致 502/504 錯誤。  
- **監控工具**：使用 HAProxy 或獨立代理進行流量監控與診斷。

