# MOSS Emphasis 0.9

**普通のPositive欄で `(big eyes:0.5)` を使用し、SettingsだけでON/OFF・Strengthを操作するComfyUI拡張です。** 専用のPrompt Weightノードを配置する必要はありません。

> **0.9は試験版です。** CPUの単体・契約テストは実施しましたが、MOSS実モデルのGPU生成、実際のComfyUI画面、Base/SFTや量子化モデルの生成品質は未検証です。完全なV1受入完了とは区別してください。

## インストール

ComfyUIの `custom_nodes` フォルダで次を実行します。

```sh
git clone https://github.com/ukr8b3g-cmyk/ComfyUI-MOSS-Emphasis.git
```

ZIPの場合は `custom_nodes/ComfyUI-MOSS-Emphasis/__init__.py` となるよう展開します。二重フォルダにしないでください。ComfyUIを再起動し、ブラウザーを再読み込みします。**追加のpip依存・モデル・LLM・KJNodesは不要**です。

ComfyUI本体のネイティブMOSS-Image対応と、現行のAttention/Settingsインターフェースを前提とします。OpenMOSSの独立HFロード用プラグインには0.9では対応しません。

## 使い方

### 画面の見方

![MOSS Emphasis設定画面（英語UIの例）](docs/images/moss-emphasis-settings.webp)

*図：英語UIでのSettings画面。ComfyUIのロケールを日本語にすると、設定名・「ⓘ」のマウスオーバーヘルプ・セクション名・プルダウン項目が日本語になります。*

| 画像の英語表示 | 日本語UIでの表示 | 用途 |
|---|---|---|
| Advanced | 詳細設定 | 詳細オプションのグループ |
| Diagnostic logging | 診断ログ | 問題の調査時に対象IDや警告をログへ出す。普段はOFF |
| General | 一般 | 普段使う設定のグループ |
| Strength | 重み付け強度 | 全体の効き具合。0.00〜4.00、標準は1.00 |
| Enable prompt weighting | プロンプトの重み付けを有効化 | **ここをONにすると機能が有効**。初期値OFF |
| Tools | ツール | 実行用データの書き出し |
| API export | APIエクスポート | 重み処理を含む実行用API JSONを保存 |
| Select action | 操作を選択 | ツール操作の未選択状態 |
| Export execution API JSON | 実行用API JSONを書き出す | API exportのプルダウン内の実行項目 |

### 通常の画像生成

1. ComfyUIで **Settings → MOSS Emphasis**（日本語UIでは **MOSS 強調設定**）を開きます。
2. **Enable prompt weighting（プロンプトの重み付けを有効化）をON**にします。
3. **Strength（重み付け強度）を1.00**に設定します。値を下げると作用が弱まり、上げると強調・抑制の両方が強まります。
4. 普段どおり **Positive側のCLIP Text Encode**、またはそこへ接続する **Text Multiline** 等に文章を入力してQueueします。専用Prompt Weightノードは不要です。

従来の配線を変更する必要はありません。

```text
Text Multiline / CSV / 文字列結合（必要な場合）
        ↓
普通の CLIP Text Encode
        ↓
KSampler の positive
```

例えば、Positive欄に次のように入力できます。

```text
portrait, (big eyes:0.5), (long hair:1.2), soft lighting
```

`(big eyes:0.5)` は「大きな目」を弱める方向、`(long hair:1.2)` は長い髪を強調する方向に作用します。**数値は実寸や出現確率を直接指定するものではありません。**

設定は**現在のワークフロー単位**です。新規ワークフローではOFFとなり、保存・読み戻し時にはそのワークフローの値を復元します。投入済みのキューには後から変更したStrengthを反映しません。MOSS Base／SFTの手動切替は不要です。

### 詳細設定とツール

- **Diagnostic logging（診断ログ）：** 問題調査時だけONにします。対象ノードID、設定、警告などを確認できますが、プロンプト全文は記録しません。
- **API export（APIエクスポート）：** プルダウンの **Export execution API JSON（実行用API JSONを書き出す）** を選ぶと、重み処理を含めたAPI実行用JSONをダウンロードします。通常のComfyUI「API形式で保存」には内部の重み処理が含まれない場合があります。
- **マウスオーバーヘルプ：** 各項目名の横にある `ⓘ` にカーソルを合わせると説明が表示されます。ComfyUIのロケールが日本語なら説明も日本語、英語なら英語になります。

**OFFまたはStrength=0.00では、構文の除去も含めて完全バイパス**です。Negative欄はそのままで、この拡張による重み指定は追加されません。KJNodes版の専用Prompt Weightノードを同じ生成経路に残したままONにすると、二重適用防止エラーになります。

### 日本語UIへの切り替え

ComfyUIの **Settings → Comfy → Locale → Language** で **日本語** を選びます。拡張が更新済みなら、MOSS Emphasisのセクション名、設定ラベル、`ⓘ` ヘルプ、API exportの選択肢が自動的に日本語へ切り替わります。日本語翻訳はComfyUI標準のカスタムノード翻訳機構を利用し、モデル・CLIP・Promptの値や設定IDは変更しません。

拡張のソースを更新した場合は、**ComfyUIを再起動してブラウザも再読み込み**してください。既存の `v0.9` リリースZIPには、このREADME画面例と日本語UI翻訳ファイルが含まれないため、GitHubの `main` を更新したものを使用してください。

## 重みの意味

`0.5`は目の大きさを半分にする指定ではありません。KJ方式の数式に従い、1以下では対象トークンのValue、1超ではAttentionスコアへ作用します。`0`や負数も概念を完全に消す保証はありません。

作品名の括弧は保持します。`saber (fate)`は普通の文字列、`(saber (fate):1.2)`は句全体の強調です。`(word)`だけでは暗黙の1.1倍強調を行いません。入れ子の明示重みは積算します。同じ単語が複数回あっても、指定した出現だけが対象です。

個別・実効重みは-2〜4、入れ子は16階層、重みグループは128個までです。文字として使うコロンや括弧が重み構文に見える場合はバックスラッシュでエスケープします。

### 注意：時計・時刻などの `(12:30)` は重み構文と誤認されます

本拡張がON（Strength > 0）のとき、`(文字列:数値)` は**重み構文**として解析されます。例えば以下の時計の時刻は、`12` が対象文字列、`30` が重みとして扱われます。

```text
A clock showing (12:30), (big eyes:0.5)
```

`30` は許容範囲（-2〜4）外のため、`INVALID_WEIGHT` エラーで**生成前に停止**します。時計の表示を強調したいわけではない場合は、次のいずれかを使ってください。

- **括弧が不要なら取り除く（推奨）：**

  ```text
  A clock showing 12:30, (big eyes:0.5)
  ```

- **括弧も表示・記述したいなら `\(` と `\)` でエスケープする：**

  ```text
  A clock showing \(12:30\), (big eyes:0.5)
  ```

実際の入力欄には、上のコードブロックに示したとおり**バックスラッシュを1文字ずつ**入力します。時刻だけでなく、`(1:2)` のような比率やセリフ中の括弧も同様に注意してください。エスケープ表記は、他に有効な重み指定がある場合に構文除去処理で普通の括弧へ戻されます。**重み指定が全くない入力では、拡張は原文を維持するため、括弧が不要なら省く方法が確実です。** OFF／Strength=0では拡張による構文解析自体を行いません。

MOSS Layout JSONでは`summary.caption`と`items[].caption`のみ処理します。看板等に描く`items[].text`、BBOX座標、その他の値を強調構文として処理しません。

## 対応範囲と注意

Base/SFTの手動切替はありません。ファイル名ではなく、ロードされたモデルとCLIPの構造を判定します。

0.9で対応する標準経路は、`CLIPTextEncode → KSampler / KSamplerAdvanced`、および`CLIPTextEncode → CFGGuider → SamplerCustomAdvanced`です。Text Multiline等は、この標準エンコーダーへSTRINGを渡す場合に使用できます。

**AttentionはPyTorch/basicの契約に限定**しています。INT8/SOL Attention設定付きの`_attn`モデル、Sage/Flashの上書き等を検出した場合、勝手にカーネルを変更せず理由を表示して停止します。量子化「重み」と量子化「Attention」は別です。実際の量子化モデル生成は未検証です。

ModelSamplingSD3と公式SLGの配線・設定は維持しますが、**SLG併用での実GPU一致は未検証**です。EasyUse等の一体型生成経路、Conditioningの平均・連結、Edit/参照画像/Control、NAG、torch.compile、Spectrum/TeaCache等は0.9の対象外です。これらでは拡張をOFFにしてください。

KJ版や独立版のPrompt Weightノードを同じ経路へ置いたままONにすると、二重適用防止エラーになります。インストールされているだけなら競合しません。

## 画面には出ない処理について

編集画面のノード・配線は変更しません。ただし送信する実行用グラフには内部ノードを追加します。**実行履歴/API JSONには内部ノードが現れます。** 設定を内部ノードの入力へ含めることで、Strength変更をキャッシュへ反映します。

通常の「API形式で保存」では適用処理を含まない場合があります。再現用には本拡張のSettingsにあるAPI exportを使用してください。画像へのメタデータ保存が元からONなら、編集用ワークフローと実行用グラフを既存経路で保存します。保存OFFを勝手にONにはしません。

削除・無効化する場合は、まずSettingsでOFFにして保存し、ComfyUIを停止してこの拡張フォルダを外します。本体やモデルファイルの復元作業は不要です。

検証内容：[VALIDATION.md](docs/VALIDATION.md)。仕様：[SPEC_0.9.md](docs/SPEC_0.9.md)。GPL-3.0-only。
