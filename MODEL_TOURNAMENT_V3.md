# Model Tournament V3

所有模型使用同一数据、同一特征、同一标签、同一五窗口划分。分类候选为 Logistic Regression、Random Forest、LightGBM、XGBoost、CatBoost；回归候选为 Linear Regression、Ridge、Lasso、LightGBM、XGBoost。Majority、Random Walk 和 Naive Momentum 为基线。

| 市场/周期 | 最佳分类器 | Balanced Acc 中位数 | MCC 中位数 | 最佳回归器 | Rank IC 中位数 |
|---|---|---:|---:|---|---:|
| A股 1D | Logistic | 0.3333 | 0.0000 | Linear | 0.030 |
| A股 T+5 | Logistic | 0.3377 | 0.0125 | Linear | 0.040 |
| A股 T+20 | Logistic | 0.3333 | 0.0000 | Lasso | 0.020 |
| 美股 1D | Logistic | 0.3333 | 0.0000 | XGBoost | 0.020 |
| 美股 T+5 | Logistic | 0.3333 | 0.0000 | Lasso | 0.030 |
| 美股 T+20 | Logistic | 0.3333 | 0.0000 | Linear | 0.060 |
| Crypto 1H | Logistic | 0.3333 | 0.0000 | Ridge | 0.010 |
| Crypto 4H | Logistic | 0.3333 | 0.0000 | LightGBM | 0.020 |
| Crypto 24H | Logistic | 0.3333 | 0.0000 | Lasso | -0.020 |
| Crypto 7D | Logistic | 0.3333 | 0.0000 | LightGBM | -0.020 |

复杂模型没有稳定优于线性模型。深度模型因当前横截面、样本量和可验证外生变量不足而不训练，状态保持 `UNQUALIFIED/EXPERIMENTAL`，不会用一个更复杂架构掩盖数据问题。
