package com.ssafy.travelmate.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ssafy.travelmate.R
import com.ssafy.travelmate.ui.theme.GoogleBorder
import com.ssafy.travelmate.ui.theme.GoogleText
import com.ssafy.travelmate.ui.theme.GoogleWhite
import com.ssafy.travelmate.ui.theme.KakaoLabel
import com.ssafy.travelmate.ui.theme.KakaoYellow
import com.ssafy.travelmate.ui.theme.NaverGreen

@Composable
fun SocialLoginButton(
    text: String,
    containerColor: Color,
    textColor: Color,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    borderColor: Color? = null,   // 테두리 색 (구글을 위해 null 허용)
    iconSlot: @Composable () -> Unit // 아이콘이 들어갈 자리
) {
    Button(
        onClick = onClick,
        modifier = modifier.height(48.dp),
        colors = ButtonDefaults.buttonColors(containerColor = containerColor),
        shape = RoundedCornerShape(6.dp),
        contentPadding = PaddingValues(horizontal = 14.dp),
        // borderColor가 null이 아닐 때만 BorderStroke를 적용
        border = borderColor?.let { BorderStroke(1.dp, it) }
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Start
        ) {
            //IconLogo
            iconSlot()

            Text(
                text = text,
                color = textColor,
                fontSize = 12.sp, // 아이콘과 함께 여러 버튼이 있을 때 텍스트가 잘릴 수 있으므로 크기 조정
                fontWeight = FontWeight.Medium,
                modifier = Modifier.weight(1f),
                textAlign = TextAlign.Center,
                maxLines = 1
            )
        }
    }
}


@Composable
fun KakaoLoginButton(modifier: Modifier = Modifier, onClick: () -> Unit) {
    SocialLoginButton(
        text = "카카오",
        containerColor = KakaoYellow,
        textColor = KakaoLabel,
        onClick = onClick,
        modifier = modifier
    ) {
        Image(
            painter = painterResource(id = R.drawable.kakaotalk_sharing_btn_small),
            contentDescription = "Kakao Logo",
            modifier = Modifier.size(24.dp)
        )
    }
}

@Composable
fun NaverLoginButton(modifier: Modifier = Modifier, onClick: () -> Unit) {
    SocialLoginButton(
        text = "네이버",
        containerColor = NaverGreen,
        textColor = Color.White,
        onClick = onClick,
        modifier = modifier
    ) {
        Image(
            painter = painterResource(id = R.drawable.naver_logo),
            contentDescription = "Naver Logo",
            modifier = Modifier.size(24.dp)
        )
    }
}

@Composable
fun GoogleLoginButton(modifier: Modifier = Modifier, onClick: () -> Unit) {
    SocialLoginButton(
        text = "Google",
        containerColor = GoogleWhite,
        textColor = GoogleText,
        borderColor = GoogleBorder,
        onClick = onClick,
        modifier = modifier
    ) {
        Image(
            painter = painterResource(id = R.drawable.google_logo),
            contentDescription = "Google Logo",
            modifier = Modifier.size(24.dp)
        )
    }
}
