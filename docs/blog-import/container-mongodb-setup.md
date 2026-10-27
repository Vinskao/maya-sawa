---
title: "container-mongodb-setup"
publishDate: "2024-03-17 12:00:00"
img: /tymultiverse/assets/container.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/03/17
category: Docker
tags:
  - MongoDB
  - Mongo Express
  - Container
---

## 目標

建立兩個 Docker Container，MongoDB Container、Mongo Express Container，其中 Mongo Express 是 MongoDB 的 GUI，兩個 Container 之間是需要連線的。

### 建立 Docker 網路

創建一個驅動類型為 bridge 的網路。

```bash
docker network create -d bridge mongo-network
```

查看當前的網路。

```bash
docker network ls
```

### 創造 Volume 以儲存 mongoDB 資料

```bash
docker volume create mongo_data_volume
```

建立完成後，mongo_data_volume 將在 Docker 的捲管理系統中註冊，並在本機檔案系統上建立目錄來儲存資料。 這個目錄將由 Docker 管理，可以將它掛載到容器中的適當位置來儲存資料。 透過建立卷，可以確保即使容器被刪除，資料也將保留，並且可以在其他容器中共享使用。

## Container 1：MongoDB

#### 從 Docker Hub 拉取 mongo 鏡像檔

```bash
docker pull mongo
```

### 部署 Docker 映像

部署映像意味著在 Docker 環境中啟動一個容器，並讓它運行特定的映像，以提供某種服務或應用程式。

-i：表示允許與容器的標準輸入互動。
-t：指派一個偽終端 (pseudo-tty)。
-d：以分離模式 (detached mode) 運作容器，在背景運作。
-auth: 啟用 MongoDB 的身份驗證機制，需要透過使用者名稱和密碼來存取資料庫。

```bash
docker run -itd --name mongo_volume -p 27017:27017 --network mongo-network -v mongo_data_volume:/data/db mongo:latest
```

### 連線到 mongoDB

```bash
docker exec -it mongo_volume mongosh --host localhost --port 27017
```

### 建立使用者

```javascript
use admin
db.createUser(
  {
    user: 'admin',
    pwd: 'password',
    roles: [ { role: 'root', db: 'admin' } ]
  }
);
exit;
```

### 登入

```javascript
db.auth("admin", "password");
```

## Container 2：Mongo Express

mongo-express 是 mongoDB 的 GUI。

#### 從 Docker Hub 拉取 mongo-express 鏡像檔

```bash
docker pull mongo-express:latest
```

### 部署 Docker 映像

這邊要寫跟上面 mongoDB 部署時所創建的 server 名稱。

```bash
docker run --name mongo_express \
--network mongo-network \
-e ME_CONFIG_MONGODB_SERVER=mongo_volume \
-e ME_CONFIG_MONGODB_ADMINUSERNAME=admin \
-e ME_CONFIG_MONGODB_ADMINPASSWORD=password \
-e ME_CONFIG_BASICAUTH_USERNAME=admin \
-e ME_CONFIG_BASICAUTH_PASSWORD=password \
-p 8081:8081 \
-d \
mongo-express:latest
```

連線成功後可以看到以下畫面：

![展示結果](/tymultiverse/assets/md-image/mongodb-express.png)

## 進階設定與資料保護

- **資料持久性：** 利用 Docker Volume 確保 MongoDB 資料長期保留，並定期備份以防資料遺失。
- **網路安全：** 建議管控容器之間的連線權限，對外公開介面需進行安全防護。
- **監控管理：** 採用工具（例如 Portainer）監控容器狀態，有助於預測與處理潛在問題。
