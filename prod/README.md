## プロジェクトのGoogle Cloudへのデプロイ手順

### 必要なツールのインストール
- Terraform: 公式サイトからダウンロードしてインストールして下さい。
- Google Cloud SDK (gcloud): インストールガイドに従ってインストールして下さい。

Terraform：  
https://developer.hashicorp.com/terraform/install

gcloud：  
https://cloud.google.com/sdk/docs/install?hl=ja

### Google Cloudへの認証とプロジェクトの設定

ターミナルで以下のコマンドを実行してGoogle Cloudに認証します
```sh
gcloud auth login
```

デプロイ先のプロジェクトを設定します：
```sh
gcloud config set project [YOUR_PROJECT_ID]
```

<img width="1341" alt="スクリーンショット 2024-11-10 12 14 36" src="https://github.com/user-attachments/assets/6955471f-7910-4784-9c0d-4c766d4bd85b">




terraformフォルダの下にあるbackend.tfファイルでTerraformの状態を保存するバックエンドを設定します
```sh
terraform {
  backend "gcs" {
    bucket  = "your-terraform-state-bucket"　# your-terraform-state-bucketは事前に作成したGoogle Cloud Storageのバケット名
  }
}
```

### デプロイ用のサービスアカウントの設定

サービスアカウントのロールの設定はIAMで以下のように設定して下さい。
<img width="1110" alt="スクリーンショット 2024-11-10 12 20 31" src="https://github.com/user-attachments/assets/3682105b-70ec-47b3-a1dc-1b16201a25ff">

その後、get-race_planとget-race_predictionとget-race_results内にあるmain.tfファイルのlocalsの部分を自分が作成したサービスアカウントに修正して下さい。

```sh
locals {
  service_account_email = "terraform@test-441303.iam.gserviceaccount.com"　# この部分
}
```

### Sercret ManegerにSlackトークンを登録
- このシステムでは予測結果をSlackに通知する構成になっています。そのため、予めGoogle CloudのSercret ManegerにSlackトークンを設定して下さい。

![スクリーンショット 2024-11-10 15 38 13](https://github.com/user-attachments/assets/694922bc-58a6-4408-b1ef-010d15645f6a)

### Terraformのコマンド実行
prod/terraformのディレクトリで以下のコマンドを実行して下さい。
```sh
terraform init
```

デプロイ内容を確認するため、以下のコマンドを実行して下さい。  
各種パラメータは自分のものを設定して下さい。

```sh
terraform plan \
  -var="project_id=your-gcp-project-id" \  # Google CloudのプロジェクトID
  -var="region=your-region" \              # Google Cloudのリージョン
  -var='sa_iam_config=[{sa_name="your-service-account-name", iam_roles=["roles/role1","roles/role2"]}]' \ # サービスアカウントのロール
  -var="netkeiba_login_id=your-login-id" \ # スクレイピングの際に利用するnetkeibaのログインID
  -var="netkeiba_login_password=your-login-password" # スクレイピングの際に利用するnetkeibaのpassword
  -var='notification_email=sample.123@gmail.com' # エラー通知を行うためのメールアドレス
```

コマンド入力例：
```sh
terraform plan \
  -var='project_id=test-441303' \
  -var='region=us-west1' \
  -var='sa_iam_config=[{sa_name="terraform", iam_roles=["roles/bigquery.jobUser","roles/bigquery.dataEditor","roles/cloudbuild.builds.editor","roles/cloudfunctions.viewer","roles/cloudfunctions.developer","roles/run.developer","roles/run.invoker","roles/cloudscheduler.admin","roles/secretmanager.secretAccessor","roles/storage.objectViewer","roles/iam.serviceAccountUser"]}]' \
  -var='netkeiba_login_id=sample.123@gmail.com' \
  -var='netkeiba_login_password=password' \
  -var='notification_email=sample.123@gmail.com'
```


リソースをデプロイするため、以下のコマンドを実行します
```sh
terraform apply
```

### デプロイした環境を動かす手順

1. データの投入
- 初期の段階ではデータは何も登録されていないので事前にスクレイピングしたデータを登録する必要があります。
- https://github.com/Kaggle-runa/MameLand_vol3/blob/main/src/notebook/00_%E3%83%87%E3%83%BC%E3%82%BF%E3%81%AE%E3%82%B9%E3%82%AF%E3%83%AC%E3%82%A4%E3%83%94%E3%83%B3%E3%82%B0.ipynb
  で作成したデータをCloud Strageの「scraping-race_results-landing-prod」に格納して下さい。
 
2. モデルの登録
- https://github.com/Kaggle-runa/MameLand_vol3/blob/main/src/notebook/03_%E3%83%A2%E3%83%87%E3%83%AB%E3%81%AE%E5%AD%A6%E7%BF%92.ipynb
  で作成したLightGBMのモデルをCloud Strageの「model_registry-prod」に格納して下さい。

3. Slack通知の登録
- Cloud Functionsの「race_prediction-prod」で予測結果をSlack通知する関数を設定しているので、こちらを使いたい場合はSlackチャンネルを作成してトークンを発行し、関数の環境変数に設定して下さい。

これで週末のレース毎に競馬の予想が動くようになります。
特徴量を増やしたりしてモデルを差し替えたい場合は「model_registry-prod」のモデルの差し替えとCloud Functionsの「race_prediction-prod」のコードを変更して下さい。
