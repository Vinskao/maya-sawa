---
title: "container-microsoft-sql-server"
publishDate: "2024-03-16 12:00:00"
img: /tymultiverse/assets/container.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/03/16
category: Docker
tags:
  - MSSQL
  - Azure SQL Edge
  - Container
---

## 前置作業

安裝 Docker。docker 相關指令需要執行 docker 才有效。

### 查看系統已經拉取的 Docker 鏡像

```bash
docker images
```

![展示結果](/tymultiverse/assets/md-image/docker-images.png)

### Azure SQL Edge vs MSSQL

Microsoft 並沒有官方支援 macOS 版本的 MSSQL Server。 但是，他們提供了適用於 macOS 的 SQL Server 相關工具，例如 SQL Server 命令列工具（mssql-tools），以及 Azure Data Studio 等，也沒有提供 MSSQL 適用於 ARM64 的鏡像，但有提供 Azure SQL Edge 的 ARM64 鏡像 。

Azure SQL Edge 是以最新版的 SQL Server 資料庫引擎 為基礎，可提供業界的 效能、安全性和查詢處理功能。

### 創造 Volume 以儲存 SQL 資料

```bash
docker volume create sql_data_volume
```

建立完成後，sql_data_volume 將在 Docker 的捲管理系統中註冊，並在本機檔案系統上建立目錄來儲存資料。 這個目錄將由 Docker 管理，可以將它掛載到容器中的適當位置來儲存資料。 透過建立卷，可以確保即使容器被刪除，資料也將保留，並且可以在其他容器中共享使用。

SQL Server 容器的資料包括：

- 資料庫檔案：包含主資料庫（master）、使用者資料庫、臨時資料庫等。 這些檔案包含實際儲存的資料、表格結構、索引等資料庫物件的資訊。

- 日誌檔案：包括交易日誌檔案、錯誤日誌檔案等。 這些文件記錄了資料庫引擎的運作日誌、交易日誌等重要資訊。

- 設定檔：包括 SQL Server 執行個體的設定檔、啟動腳本等。 這些檔案用於配置 SQL Server 執行個體的參數、權限、存取控制等。

- 備份檔案：包括資料庫備份檔案、日誌備份檔案等。 這些檔案用於恢復資料庫、遷移資料、進行資料備份等操作。

#### 查看現有 volume

```bash
docker volume ls
```

![展示結果](/tymultiverse/assets/md-image/docker-volume.png)

### 從 Docker Hub 拉取鏡像檔

##### Mac OS 使用 azure-sql-edge

```bash
docker pull mcr.microsoft.com/azure-sql-edge:latest
```

##### Windows OS 使用 mssql/server

```shell
docker pull mcr.microsoft.com/mssql/server:latest
```

### 部署 SQL 鏡像

部署鏡像意味著在 Docker 環境中啟動一個容器，並讓它運行特定的映像，以提供某種服務或應用程式。

#### Mac OS 部署 azure-sql-edge

##### 沒有 volume 的版本

```bash
sudo docker run -e "ACCEPT_EULA=Y" -e "MSSQL_SA_PASSWORD=YourStrongPassword" \
   -e "MSSQL_COLLATION=Chinese_Taiwan_Stroke_CI_AI" \
   -e "TZ=Asia/Taipei" \
   -p 1433:1433 --name sql --hostname sql \
   -d \
   mcr.microsoft.com/azure-sql-edge
```

##### 將容器備份到本機

```bash
docker cp sql:/var/opt/mssql /Users/vinskao/volume/temp
```

##### 透過本機 volume 存取資料，建立新容器

```bash
sudo docker run -e "ACCEPT_EULA=Y" \
   -e "MSSQL_SA_PASSWORD=YourStrongPassword" \
   -e "MSSQL_COLLATION=Chinese_Taiwan_Stroke_CI_AI" \
   -e "TZ=Asia/Taipei" \
   -p 1433:1433 \
   --name sql_volume \
   --hostname sql_volume \
   -v /Users/vinskao/volume/temp:/var/opt/mssql \
   -d \
   mcr.microsoft.com/azure-sql-edge
```

進入 Docker Desktop 可以看到 volume 位置：
![展示結果](/tymultiverse/assets/md-image/sql-volume.png)

## 容器運維與性能調優

- **數據備份：** 利用 Volume 保存 SQL 資料，並規劃定期備份策略以防故障。
- **環境安全：** 確保 MSSQL 容器的密碼強度與網路存取管控，防止未授權存取。
- **資源監控：** 使用 Docker 監控工具（如 cAdvisor）持續監控容器資源使用，進行適時調整。
