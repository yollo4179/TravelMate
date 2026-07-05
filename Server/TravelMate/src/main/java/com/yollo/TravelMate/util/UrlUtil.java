package com.yollo.TravelMate.util;

public class UrlUtil {

	
	static public String extractHomepageUrl(String homepageRaw) {
	    if (homepageRaw == null || homepageRaw.isBlank()) return null;
	    // <a href="URL" ...>텍스트</a> 형태에서 href 값만 추출
	    java.util.regex.Matcher m =
	        java.util.regex.Pattern.compile("href=\"([^\"]+)\"").matcher(homepageRaw);
	    return m.find() ? m.group(1) : null;
	}
}
